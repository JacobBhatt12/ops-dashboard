"""Campaign regression tests run entirely against temporary databases.

Gmail, notifications, sleep, and scanner are mocked: no messages leave.
"""
import copy
import fcntl
from datetime import date
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agencyfinder import api as agency_api
from agencyfinder import settings as S
from agencyfinder.bridge import take_agencies
from agencyfinder.scrape import clean_site, is_agency, state_code
from agencyfinder.store import AgencyStore
from agencyfinder.template import render_agency
from bot import run_daily
from bot.campaigns import alternate, budget, sent_count
from bot.config import Config
from bot.contacts import Contact
from bot.message import SIGNATURE_HTML, SIGNATURE_TEXT
from bot.store import Store


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.outreach_path = self.root / "outreach.db"
        self.agency_path = self.root / "agencies.db"
        self.cfg = copy.deepcopy(Config.load()._d)
        for key in self.cfg["paths"]:
            self.cfg["paths"][key] = str(self.root / key)
        self.cfg["paths"]["state_db"] = str(self.outreach_path)
        Path(self.cfg["paths"]["contacts_xlsx"]).touch()
        self.cfg["volume"]["daily_target"] = 150
        self.cfg["schedule"]["weekdays_only"] = False
        self.contacts = [Contact(f"person{i}@example.org", f"Person{i}", f"Last{i}", None,
                                 "Client", None) for i in range(200)]
        st = AgencyStore(self.agency_path)
        for i in range(200):
            st.insert({"place_id": str(i), "name": f"Agency {i}", "category": "Website designer",
                       "domain": f"agency{i}.example", "website": f"https://agency{i}.example",
                       "email": f"hello@agency{i}.example", "city": "Tampa", "state": "FL",
                       "status": "ready"})
        st.close()

    def run_sender(self, args=None, scan_error=None):
        calls = []
        def fake_send(email, subject, text, html):
            calls.append((email, text))
            return f"message-{len(calls)}", "thread"
        with (patch.object(run_daily.Config, "load", side_effect=lambda *_: Config(copy.deepcopy(self.cfg))),
              patch.object(run_daily, "ROOT", self.root),
              patch.object(run_daily, "load_contacts", return_value=self.contacts),
              patch.object(run_daily, "self_check"),
              patch.object(run_daily, "setup_logging", return_value=__import__("logging").getLogger("test")),
              patch.object(run_daily, "notify"),
              patch.object(run_daily, "scan", side_effect=scan_error,
                           return_value={"scanned": 0, "optouts": 0, "bounces": 0}),
              patch.object(run_daily.time, "sleep"),
              patch.object(run_daily.lead_settings, "load", return_value={"contact_list_enabled": True}),
              patch.object(S, "load", return_value={**S.DEFAULTS, "send_enabled": True, "per_day": 150, "auto_approve": True}),
              patch.object(S, "DB_PATH", self.agency_path),
              patch.object(run_daily, "GmailClient") as gmail):
            gmail.return_value.send.side_effect = fake_send
            result = run_daily.main(args if args is not None else ["--now", "--no-scan"])
        return result, calls

    def test_daily_caps_alternation_and_same_day_restart(self):
        result, calls = self.run_sender()
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 300)
        streams = ["agency" if AGENCY_MARK in text else "client" for _, text in calls]
        self.assertEqual(streams, ["client", "agency"] * 150)
        st = Store(self.outreach_path)
        self.assertEqual(sent_count(st, date.today(), "client"), 150)
        self.assertEqual(sent_count(st, date.today(), "agency"), 150)
        st.close()
        result, calls = self.run_sender()
        self.assertEqual(result, 0)
        self.assertEqual(calls, [])

    def test_partial_day_uses_separate_remaining_budgets(self):
        st = Store(self.outreach_path)
        for i in range(149):
            c = SimpleNamespace(email=f"old{i}@example.org", person_key=f"old{i}",
                                first_raw=None, last=None, company="Old")
            st.record_send(c, template="agency")
        for i in range(148):
            st.record_send(SimpleNamespace(email=f"past{i}@example.org", person_key=f"past{i}",
                                           first_raw=None, last=None, company="Past"))
        st.close()
        result, calls = self.run_sender()
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 3)
        self.assertIn(AGENCY_MARK, calls[0][1])
        st = Store(self.outreach_path)
        self.assertEqual(sent_count(st, date.today(), "agency"), 150)
        self.assertEqual(sent_count(st, date.today(), "client"), 150)
        st.close()

    def test_queue_shortfall_never_increases_client_cap(self):
        st = AgencyStore(self.agency_path)
        st.conn.execute("UPDATE agencies SET status='rejected' WHERE id > 2")
        st.conn.commit()
        st.close()
        _, calls = self.run_sender()
        self.assertEqual(len(calls), 152)
        self.assertEqual(sum(AGENCY_MARK in text for _, text in calls), 2)

    def test_failed_scan_stops_both_campaigns(self):
        result, calls = self.run_sender(["--now"], scan_error=RuntimeError("scan unavailable"))
        self.assertEqual(result, 2)
        self.assertEqual(calls, [])

    def test_hourly_runs_split_the_remaining_budget(self):
        # The current local hour is used by the sender; give it a 12-hour
        # window from a deterministic 9am clock.
        from datetime import datetime
        class NineAM(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls.combine(date.today(), cls.min.time()).replace(hour=9)
        self.cfg["schedule"].update(start_hour=9, end_hour=21)
        with patch.object(run_daily, "datetime", NineAM):
            result, calls = self.run_sender(["--hourly", "--now", "--no-scan"])
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 26)  # ceil(150 / 12) from each campaign
        self.assertEqual(sum(AGENCY_MARK in text for _, text in calls), 13)

    def test_shared_api_ceiling_applies_to_both_campaigns(self):
        self.cfg["safety"]["daily_api_ceiling"] = 10
        _, calls = self.run_sender()
        self.assertEqual(len(calls), 10)

    def test_large_cli_limit_cannot_raise_client_cap(self):
        _, calls = self.run_sender(["--now", "--no-scan", "--limit", "300"])
        self.assertEqual(len(calls), 300)
        self.assertEqual(sum(AGENCY_MARK in text for _, text in calls), 150)

    def test_overlapping_sender_is_skipped(self):
        (self.root / "data").mkdir()
        with (self.root / "data" / "outreach.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result, calls = self.run_sender()
        self.assertEqual(result, 0)
        self.assertEqual(calls, [])

    def test_dry_run_does_not_send_or_record(self):
        result, calls = self.run_sender(["--dry-run", "--now", "--no-scan"])
        self.assertEqual(result, 0)
        self.assertEqual(calls, [])
        st = Store(self.outreach_path)
        self.assertEqual(st.count_sent_on(date.today()), 0)
        st.close()

    def test_global_blocks_and_sent_history_exclude_agencies(self):
        st = Store(self.outreach_path)
        st.block("hello@agency0.example", "unsubscribe", "optout")
        st.record_send(SimpleNamespace(email="hello@agency1.example", person_key="old",
                                      first_raw=None, last=None, company="Old"))
        with patch.object(S, "DB_PATH", self.agency_path):
            contacts, ls = take_agencies(st, 200, include_ready=True)
        self.assertEqual(len(contacts), 198)
        self.assertNotIn("hello@agency0.example", {c.email for c in contacts})
        self.assertNotIn("hello@agency1.example", {c.email for c in contacts})
        ls.close()
        st.close()

    def test_agency_message_has_the_pitch_and_signature_once(self):
        for name in ("Grove Brands LLC", "", "<Dana & Co>"):
            row = {"name": name, "category": "SEO agency", "city": "Austin", "state": "TX"}
            subject, text, html = render_agency(row)
            self.assertIn("hundreds of dollars a month on ads", text)
            self.assertIn("thousands a year", text)
            self.assertIn("I was a student", text)
            self.assertIn(AGENCY_MARK, text)
            self.assertIn("anywhere in Texas or across the whole country", text)
            self.assertIn("SEO and marketing agencies in Austin", text)
            self.assertEqual(subject, "finding new clients in Austin")
            self.assertEqual(text.count(SIGNATURE_TEXT), 1)
            self.assertEqual(html.count(SIGNATURE_HTML), 1)
            self.assertIn("unsubscribe", text)
            self.assertNotIn("\u2014", text)
        self.assertIn("&lt;Dana &amp; Co&gt;", html)

    def test_scraper_rows_are_filtered_and_cleaned(self):
        row = {"title": "Smartly Done Websites", "category": "Website designer",
               "categories": ["Website designer", "Marketing agency"],
               "complete_address": {"city": "Tampa", "state": "Florida", "country": "US"}}
        self.assertTrue(is_agency(row))
        self.assertEqual(state_code(row), "FL")
        self.assertFalse(is_agency({"category": "Pizza restaurant", "categories": []}))
        self.assertEqual(state_code({"address": "1 Main St, Austin, TX 78701"}), "TX")
        self.assertEqual(clean_site("https://www.smartlydone.com/tampa?utm_source=google"),
                         ("https://www.smartlydone.com/", "smartlydone.com"))
        self.assertEqual(clean_site("https://www.google.com/maps/x"), (None, None))

    def test_budgets_and_unequal_queue_alternation(self):
        self.assertEqual(budget(150, 149, 12), 1)
        self.assertEqual(budget(150, 151, 1), 0)
        self.assertEqual(budget(300, 0), 150)
        c = lambda e: SimpleNamespace(email=e)
        batch = alternate([c("a"), c("b")], [c("b"), c("c")], "client")
        self.assertEqual(len({item.email for item in batch}), len(batch))
        self.assertEqual(batch[0].email, "b")

    def test_settings_reject_invalid_values_without_writes(self):
        with patch.object(S, "SETTINGS_PATH", self.root / "settings.json"):
            for payload in ({"per_day": 151}, {"per_day": -1}, {"states": ["ZZ"]},
                            {"search_terms": []}, {"search_terms": ["x" * 61]}):
                with self.assertRaises(ValueError):
                    agency_api.update_settings(payload)
            self.assertFalse((self.root / "settings.json").exists())
            cfg = agency_api.update_settings({"per_day": 100, "states": ["fl"]})
            self.assertEqual(S.load()["per_day"], 100)
            self.assertEqual(cfg["states"], ["FL"])


AGENCY_MARK = "200+ qualified"


if __name__ == "__main__":
    unittest.main()

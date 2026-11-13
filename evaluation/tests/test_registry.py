"""
單位登記表（evaluation/registry/registry.json）與引用它的 keypoint 的測試。

  - 登記表裡每一條引句都在來源檔裡；故意改壞一條要被抓到
  - 姓名＋分機、樓層、表單連結的比對：全名／姓氏＋職稱／姓氏＋小姐都算對，名字配錯分機算 wrong，沒有姓名的分機附職稱算對
  - 條件式的 keypoint 在答案沒提到該單位（表單）時不適用、不計入
  - gold_check 接受引用登記表的 keypoint，單位／組別／表單不存在要報錯
  - score_programmatic.accuracy 對這類 keypoint 的計分
"""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  路徑與環境設定
import registry_lib as R
from gold_check import validate_gold
from score_programmatic import accuracy

REG = R.load()


class RegistrySourcesTest(unittest.TestCase):
    def test_every_quote_is_in_its_source(self):
        self.assertEqual(R.validate(REG), [])

    def test_a_tampered_quote_is_caught(self):
        bad = copy.deepcopy(REG)
        bad["offices"]["registrar"]["staff"][0]["names"][0]["sources"][0]["quote"] = "王大明"
        problems = R.validate(bad)
        self.assertEqual(len(problems), 1)
        self.assertIn("王大明", problems[0])

    def test_both_forms_are_recorded_for_every_registrar_person(self):
        for e in REG["offices"]["registrar"]["staff"]:
            forms = {(n["form"], tuple(sorted(s["source"] for s in n["sources"]))) for n in e["names"]}
            self.assertIn(("full", ("snapshot",)), forms, e["ext"])
            self.assertIn(("surname_title", ("live",)), forms, e["ext"])

    def test_title_only_entries_have_no_names(self):
        titled = [e for e in REG["offices"]["oic"]["staff"] if e["status"] == "title-only"]
        self.assertEqual(sorted(e["ext"] for e in titled), ["62025", "62815"])
        self.assertTrue(all(not e["names"] and e["titles"] for e in titled))

    def test_62058_gets_its_full_name_from_a_page_that_pairs_name_and_extension(self):
        e = next(e for e in REG["offices"]["oic"]["staff"] if e["ext"] == "62058")
        self.assertEqual([n["value"] for n in e["names"]], ["徐維勵"])


class SleepOfAbsenceOfficesTest(unittest.TestCase):
    """第 5 題（休學）新增的單位：出納組、住宿組、原資中心、圖書館，以及註冊組代表線 63279。"""

    def staff(self, office):
        return {e["ext"]: e for e in REG["offices"][office]["staff"]}

    def test_cashier_now_reads_the_new_nccuga_page_and_one_extension_is_vacant(self):
        staff = {e["ext"]: e for e in REG["offices"]["cashier"]["staff"]}
        self.assertEqual(len(staff), 11)
        self.assertEqual(sum(e["status"] == "both" for e in staff.values()), 10)
        # 62173：新頁面的姓名欄是「待補」，只有快照有名字（鄭雅玲）
        self.assertEqual(staff["62173"]["status"], "snapshot-only")
        self.assertEqual([n["value"] for n in staff["62173"]["names"]], ["鄭雅玲"])
        self.assertIn("62120", {ln["value"] for ln in REG["offices"]["cashier"]["lines"]})

    def test_the_eight_general_affairs_units_record_where_to_find_them(self):
        keys = ["ga_dean", "docu", "aff", "wealth", "mend", "cashier", "safety", "planning"]
        for k in keys:
            w = REG["offices"][k]["where_to_find"]
            self.assertTrue(w[0]["url"].startswith("https://nccuga.nccu.edu.tw/zh/"), k)
            self.assertIn("200", w[0]["status"], k)
        # 環安組的舊索引記錄叫「環境保護與職業安全衛生組」（environ.nccu.edu.tw），登記表要對上它
        self.assertIn("environ.nccu.edu.tw", REG["offices"]["safety"]["where_to_find"][1]["url"])
        self.assertIn("環境保護與職業安全衛生組", REG["offices"]["safety"]["aliases"])
        self.assertIn("evidence", REG["offices"]["cashier"]["where_to_find"][1])

    def test_same_extension_with_a_different_person_is_marked_changed_and_both_names_are_kept(self):
        e = self.staff("dorm")["67161"]
        self.assertEqual(e["status"], "changed")
        self.assertEqual({n["value"] for n in e["names"]}, {"張君豪", "陳源宗"})

    def test_placeholder_names_are_not_recorded(self):
        for o in REG["offices"].values():
            for e in o["staff"]:
                self.assertFalse(any("待" in n["value"] for n in e["names"]), e["ext"])

    def test_registrar_representative_line_63279_comes_from_the_refund_page(self):
        lines = REG["offices"]["registrar"]["lines"]
        self.assertEqual([ln["value"] for ln in lines], ["63279"])
        self.assertEqual({s["source"] for s in lines[0]["sources"]}, {"snapshot", "live"})

    def test_six_digit_extensions_of_the_repair_unit_are_recorded_as_extensions(self):
        e = {x["ext"]: x for x in REG["offices"]["mend"]["staff"]}
        self.assertEqual([n["value"] for n in e["472013"]["names"]], ["林永輝"])
        self.assertEqual(R.check_who("營繕組林永輝（分機 472013）", REG, "mend")["verdict"], "hit")
        self.assertEqual(R.check_who("營繕組林永輝（分機 47201）", REG, "mend")["verdict"], "wrong")      # 名字配錯分機（被截成 5 位數）

    def test_library_has_people_but_no_floor(self):
        self.assertTrue(REG["offices"]["library"]["staff"])
        self.assertEqual(REG["offices"]["library"]["floors"], [])

    def test_both_the_old_and_the_new_person_of_a_changed_extension_score(self):
        for name in ("張君豪", "陳源宗"):
            self.assertEqual(R.check_who(f"住宿組{name}（分機 67161）", REG, "dorm")["verdict"], "hit", name)


class CheckWhoTest(unittest.TestCase):
    def v(self, answer, office):
        return R.check_who(answer, REG, office)["verdict"]

    def test_full_name_surname_title_and_surname_honorific_all_count(self):
        for a in ("註冊組王揚忠（分機 63273）", "註冊組王組長 63273", "註冊組王小姐 63273"):
            with self.subTest(a=a):
                self.assertEqual(self.v(a, "registrar"), "hit")

    def test_name_with_the_wrong_extension_is_wrong(self):
        self.assertEqual(self.v("註冊組王組長 63274", "registrar"), "wrong")
        self.assertEqual(self.v("國合處徐維勵 62510", "oic"), "wrong")

    def test_no_name_extension_with_title_is_a_hit(self):
        self.assertEqual(self.v("國合處計畫專員（分機 62815）", "oic"), "hit")

    def test_representative_line_alone_is_a_hit_for_international_cooperation(self):
        self.assertEqual(self.v("國合處請洽 02-29393091轉67729", "oic"), "hit")

    def test_surname_honorific_may_belong_to_another_office(self):
        # 盧小姐：國合處有一位姓盧的小姐（62833），生僑組的盧誼甄（62226）也可以寫成盧小姐；兩邊都不算錯
        self.assertEqual(self.v("生僑組盧小姐（分機 62226）", "soa"), "hit")
        self.assertEqual(self.v("生僑組盧小姐（分機 62226）", "oic"), "miss")
        self.assertEqual(self.v("國合處盧小姐（分機 62833）", "oic"), "hit")

    def test_name_without_extension_is_a_miss(self):
        self.assertEqual(self.v("註冊組王揚忠", "registrar"), "miss")

    def test_unknown_extension_is_flagged_for_review_not_wrong(self):
        r = R.check_who("註冊組王揚忠 63273，系所請洽 12345", REG, "registrar")
        self.assertEqual(r["verdict"], "hit")
        self.assertEqual(r["unknown_extensions"], ["12345"])


class CheckFloorAndFormTest(unittest.TestCase):
    def test_floor_written_either_way_near_the_office_name(self):
        for a in ("國際合作事務處（行政大樓8樓）", "國合處在八樓"):
            self.assertEqual(R.check_floor(a, REG, "oic", "國際教育組")["verdict"], "hit", a)

    def test_wrong_floor_is_wrong_and_no_floor_is_a_miss(self):
        self.assertEqual(R.check_floor("國合處在三樓", REG, "oic", "國際教育組")["verdict"], "wrong")
        self.assertEqual(R.check_floor("國合處請洽國際教育組", REG, "oic", "國際教育組")["verdict"], "miss")

    def test_floor_far_from_the_name_but_on_the_same_bullet_counts(self):
        a = "- 生僑組（僅男生及僑生需辦理）：請繳交歸屬證書正本、體位證書正本或退伍令影本，在行政大樓三樓，聯絡人盧誼甄"
        self.assertEqual(R.check_floor(a, REG, "soa", None)["verdict"], "hit")

    def test_a_floor_belonging_to_another_line_does_not_count(self):
        self.assertEqual(R.check_floor("- 生僑組蓋章\n- 註冊組在行政大樓四樓", REG, "soa", None)["verdict"], "miss")

    def test_mainland_affairs_group_is_on_the_seventh_floor(self):
        self.assertEqual(R.check_floor("國合處大陸事務組在七樓", REG, "oic", "大陸事務組")["verdict"], "hit")
        self.assertEqual(R.check_floor("國合處大陸事務組在八樓", REG, "oic", "大陸事務組")["verdict"], "miss")

    def test_form_link_is_required_only_when_the_form_is_mentioned(self):
        poa = "QP-T01-02-05"
        url = REG["forms"][1]["url"]
        self.assertEqual(R.check_form_link("非本人需附委託書", REG, poa, "conditional")["verdict"], "miss")
        self.assertEqual(R.check_form_link(f"需附委託書 {url}", REG, poa, "conditional")["verdict"], "hit")
        self.assertEqual(R.check_form_link("與委託書無關的答案", REG, poa, "conditional")["verdict"], "miss")
        self.assertEqual(R.check_form_link("完全沒提", REG, "QP-T01-02-05", "conditional")["verdict"], "not_applicable")

    def test_always_mode_needs_the_link_even_when_not_mentioned(self):
        self.assertEqual(R.check_form_link("完全沒提", REG, "QP-T01-03-04", "always")["verdict"], "miss")


def _gold(keypoints):
    return {"query_id": "t", "query": "q", "content": "c", "data_as_of": {}, "keypoints": keypoints}


class GoldWithRegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "sources" / "snapshot").mkdir(parents=True)
        (self.tmp / "sources" / "snapshot" / "s.txt").write_text("來源文字", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, kps):
        (self.tmp / "gold.json").write_text(json.dumps(_gold(kps), ensure_ascii=False), encoding="utf-8")
        return validate_gold(self.tmp / "gold.json")

    def kp(self, **registry):
        return {"id": "K1", "text": "x", "kind": "hard", "value_check": "registry_who", "registry": registry}

    def test_registry_keypoint_needs_no_references_of_its_own(self):
        self.assertEqual(self.check([self.kp(office="registrar", need="who")]), [])

    def test_unknown_office_unit_or_form_is_reported(self):
        self.assertTrue(any("不在登記表" in p for p in self.check([self.kp(office="nowhere", need="who")])))
        self.assertTrue(any("沒有組別" in p for p in self.check([self.kp(office="oic", need="floor", unit="不存在組")])))
        self.assertTrue(any("不在登記表" in p for p in self.check([self.kp(need="form_link", form="QP-X")])))

    def test_missing_value_check_is_reported(self):
        k = self.kp(office="registrar", need="who")
        del k["value_check"]
        self.assertTrue(any("value_check" in p for p in self.check([k])))


class AccuracyWithRegistryTest(unittest.TestCase):
    KPS = [
        {"id": "Kr", "text": "註冊組找誰", "kind": "hard", "value_check": "registry_who", "registry": {"office": "registrar", "need": "who"}},
        {"id": "Ks", "text": "生僑組找誰", "kind": "hard", "value_check": "registry_who", "registry": {"office": "soa", "need": "who", "conditional": True}},
        {"id": "Kf", "text": "國合處樓層", "kind": "hard", "value_check": "registry_floor", "registry": {"office": "oic", "need": "floor", "unit": "國際教育組", "conditional": True}},
    ]

    def run_acc(self, answer):
        summary, rows = accuracy(_gold(self.KPS), answer, [])
        return summary, {r["id"]: r["verdict"] for r in rows}

    def test_conditional_offices_not_mentioned_are_not_counted(self):
        s, v = self.run_acc("請洽註冊組王組長（分機 63273）。")
        self.assertEqual(v, {"Kr": "hit", "Ks": "not_applicable", "Kf": "not_applicable"})
        self.assertEqual((s["hard_keypoints"], s["hit"]), (1, 1))

    def test_mentioned_offices_are_scored(self):
        s, v = self.run_acc("註冊組王組長 63273；生僑組盧誼甄 62226；國合處在行政大樓八樓。")
        self.assertEqual(v, {"Kr": "hit", "Ks": "hit", "Kf": "hit"})
        self.assertEqual((s["hard_keypoints"], s["hit"]), (3, 3))

    def test_mentioned_but_wrong_is_counted_against(self):
        s, v = self.run_acc("註冊組王組長 63273；生僑組盧誼甄 62224。")
        self.assertEqual(v["Ks"], "wrong")
        self.assertEqual(s["hit"], 1)


if __name__ == "__main__":
    unittest.main()

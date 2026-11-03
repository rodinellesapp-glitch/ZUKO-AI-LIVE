import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))

from abrir_zuko_v2 import runtime_identity_lines
from live_logger import SessionLogger


class RuntimeIdentityLoggingTests(unittest.TestCase):
    def test_runtime_and_module_hashes_fit_logger_limit_as_valid_json(self):
        runtime={"pid":1234,"python":r"C:\Python311\python.exe",
                 "cwd":str(ROOT),"entry":str(ROOT/"abrir_zuko_v2.py")}
        names=("live_monitor","zuko_presenter","zuko_litellm","live_dashboard_v2")
        modules={name:{"path":str(ROOT/"live_social_01"/(name+".py")),"sha256":"a"*64}
                 for name in names}
        lines=runtime_identity_lines(runtime,modules)
        self.assertEqual(len(lines),1+len(modules))
        self.assertTrue(all(len(line)<=800 for line in lines))
        saved=[SessionLogger.redact(line) for line in lines]
        decoded=[json.loads(line.split(" | ",1)[1]) for line in saved]
        self.assertEqual(decoded[0]["pid"],runtime["pid"])
        self.assertEqual({item["name"]:item["sha256"] for item in decoded[1:]},
                         {name:info["sha256"] for name,info in modules.items()})


if __name__=="__main__":unittest.main()

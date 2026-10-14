import os, subprocess, tempfile, shutil, unittest
from helpers import *


def git(d, *a):
    return subprocess.run(["git", "-C", d, *a], capture_output=True, text=True, check=True).stdout


class GitSync(MockBase):
    def test_commits_pushed_and_app_edits_in_between_do_not_conflict(self):
        os.environ.pop("REELIO_NO_GIT", None)
        try:
            bare = os.path.join(self.tmp, "bare.git"); subprocess.run(["git", "init", "--bare", "-b", "main", bare], check=True, capture_output=True)
            # the 'app' clone (what the browser UI edits through the GitHub API) and the worker's checkout
            self.add_drive(3)
            subprocess.run(["git", "clone", bare, self.data], check=True, capture_output=True)
            for k, v in (("user.name", "t"), ("user.email", "t@t")): git(self.data, "config", k, v)
            self.write_env(); git(self.data, "add", "-A"); git(self.data, "commit", "-m", "init"); git(self.data, "push", "-u", "origin", "HEAD:main")
            app = os.path.join(self.tmp, "app_clone"); shutil.rmtree(app, ignore_errors=True)
            subprocess.run(["git", "clone", bare, app], check=True, capture_output=True)
            for k, v in (("user.name", "app"), ("user.email", "a@a")): git(app, "config", k, v)

            # while the worker is mid-run, the app pushes a new inbox command
            W = self.W
            fired = []
            def hook(c):
                if fired: return
                fired.append(1)
                os.makedirs(os.path.join(app, "inbox"), exist_ok=True)
                open(os.path.join(app, "inbox", "x.json"), "w").write('{"cmd":"rescan","route":"r1"}')
                git(app, "add", "-A"); git(app, "commit", "-m", "ui"); git(app, "pull", "--rebase"); git(app, "push")
            W.publish_hook = hook
            self.run_engine()
            self.assertEqual(len(W.ig_posts), 3)
            git(app, "pull", "--rebase")
            log = git(app, "log", "--oneline")
            self.assertIn("posted", log); self.assertIn("ui", log)
            ledger = util.read_json(os.path.join(app, "ledger.json"))
            self.assertEqual(len(ledger["entries"]), 3, "ledger must be on GitHub after every post")
            self.assertEqual(git(self.data, "status", "--porcelain").strip(), "")
        finally:
            os.environ["REELIO_NO_GIT"] = "1"


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from unittest import mock

import setup


class ReadTokenTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"NOTION_TOKEN": "stale-token"}, clear=True)
    @mock.patch("setup.getpass.getpass", return_value="fresh-token")
    @mock.patch("setup._check_token")
    def test_rotated_env_token_falls_through_to_a_prompt(self, check, getpass):
        check.side_effect = [mock.Mock(status_code=401), mock.Mock(status_code=200)]

        self.assertEqual(setup.read_token(), "fresh-token")
        self.assertEqual(getpass.call_count, 1)
        self.assertEqual(check.call_args_list[0].args[0], "stale-token")
        self.assertEqual(check.call_args_list[1].args[0], "fresh-token")

    @mock.patch.dict(os.environ, {"NOTION_TOKEN": "stale-token"}, clear=True)
    @mock.patch("setup.getpass.getpass", return_value="also-bad")
    @mock.patch("setup._check_token", return_value=mock.Mock(status_code=401))
    def test_freshly_typed_token_that_is_rejected_exits(self, check, getpass):
        with self.assertRaises(SystemExit):
            setup.read_token()
        self.assertEqual(getpass.call_count, 1)
        self.assertEqual(check.call_count, 2)

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("setup.getpass.getpass", return_value="typed-token")
    @mock.patch("setup._check_token", return_value=mock.Mock(status_code=401))
    def test_prompted_token_is_not_re_prompted(self, check, getpass):
        with self.assertRaises(SystemExit):
            setup.read_token()
        self.assertEqual(getpass.call_count, 1)
        self.assertEqual(check.call_count, 1)

    @mock.patch.dict(os.environ, {"NOTION_TOKEN": "stored-token"}, clear=True)
    @mock.patch("setup.getpass.getpass")
    @mock.patch("setup._check_token",
                return_value=mock.Mock(status_code=500, text="server error"))
    def test_non_401_failure_still_exits_without_prompting(self, check, getpass):
        with self.assertRaises(SystemExit):
            setup.read_token()
        getpass.assert_not_called()

    @mock.patch.dict(os.environ, {"NOTION_TOKEN": "valid-token"}, clear=True)
    @mock.patch("setup.getpass.getpass")
    @mock.patch("setup._check_token", return_value=mock.Mock(status_code=200))
    def test_valid_stored_token_is_reused_without_prompting(self, check, getpass):
        self.assertEqual(setup.read_token(), "valid-token")
        getpass.assert_not_called()


class SetupWizardTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("setup._load_dotenv")
    @mock.patch("setup.push_or_print_secrets")
    @mock.patch("setup.write_env", return_value="/tmp/test.env")
    @mock.patch("setup.getpass.getpass", side_effect=["", "", ""])
    @mock.patch("setup.read_username", return_value="alice")
    @mock.patch("setup.existing_env_db", return_value="database-id")
    @mock.patch("setup.read_token", return_value="notion-token")
    def test_wizard_completes_with_every_optional_item_skipped(
        self, read_token, existing_db, read_username, getpass, write_env,
        push_secrets, load_dotenv
    ):
        setup.main()

        updates = write_env.call_args.args[0]
        defaults = write_env.call_args.kwargs["defaults"]
        self.assertEqual(updates, {
            "NOTION_TOKEN": "notion-token",
            "NOTION_DATABASE_ID": "database-id",
            "LEETCODE_USERNAME": "alice",
        })
        self.assertEqual(defaults, {
            "LEETCODE_SESSION": "",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
        })
        pushed = push_secrets.call_args.args[0]
        self.assertEqual(pushed["LEETCODE_SESSION"], "")
        self.assertEqual(pushed["ANTHROPIC_API_KEY"], "")
        self.assertEqual(pushed["OPENAI_API_KEY"], "")

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("setup._load_dotenv")
    @mock.patch("setup.push_or_print_secrets")
    @mock.patch("setup.write_env", return_value="/tmp/test.env")
    @mock.patch(
        "setup.getpass.getpass",
        side_effect=["session-cookie", "anthropic-key", "openai-key"],
    )
    @mock.patch("setup.read_username", return_value="alice")
    @mock.patch("setup.existing_env_db", return_value="database-id")
    @mock.patch("setup.read_token", return_value="notion-token")
    def test_wizard_completes_with_every_optional_item_provided(
        self, read_token, existing_db, read_username, getpass, write_env,
        push_secrets, load_dotenv
    ):
        setup.main()

        updates = write_env.call_args.args[0]
        self.assertEqual(updates["LEETCODE_SESSION"], "session-cookie")
        self.assertEqual(updates["ANTHROPIC_API_KEY"], "anthropic-key")
        self.assertEqual(updates["OPENAI_API_KEY"], "openai-key")
        self.assertEqual(write_env.call_args.kwargs["defaults"], {})
        self.assertEqual(push_secrets.call_args.args[0], updates)

    @mock.patch.dict(
        os.environ,
        {"ANTHROPIC_API_KEY": "key-from-env-file", "OPENAI_API_KEY": ""},
        clear=True,
    )
    @mock.patch("setup._load_dotenv")
    @mock.patch("setup.push_or_print_secrets")
    @mock.patch("setup.write_env", return_value="/tmp/test.env")
    @mock.patch("setup.getpass.getpass", side_effect=["", "", ""])
    @mock.patch("setup.read_username", return_value="alice")
    @mock.patch("setup.existing_env_db", return_value="database-id")
    @mock.patch("setup.read_token", return_value="notion-token")
    def test_already_configured_secrets_are_kept_and_pushed(
        self, read_token, existing_db, read_username, getpass, write_env,
        push_secrets, load_dotenv
    ):
        setup.main()

        load_dotenv.assert_called_once()
        self.assertEqual(
            write_env.call_args.args[0]["ANTHROPIC_API_KEY"], "key-from-env-file"
        )
        self.assertEqual(
            push_secrets.call_args.args[0]["ANTHROPIC_API_KEY"], "key-from-env-file"
        )

    def test_write_env_records_optional_values_and_preserves_existing_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, ".env")
            with open(path, "w") as env_file:
                env_file.write("SYNC_LIMIT=10\n")

            setup.write_env(
                {"LEETCODE_SESSION": "cookie", "OPENAI_API_KEY": "key"},
                defaults={"ANTHROPIC_API_KEY": ""},
                path=path,
            )

            with open(path) as env_file:
                contents = env_file.read()
        self.assertIn("SYNC_LIMIT=10", contents)
        self.assertIn("LEETCODE_SESSION=cookie", contents)
        self.assertIn("OPENAI_API_KEY=key", contents)
        self.assertIn("ANTHROPIC_API_KEY=", contents)

    @mock.patch("setup.subprocess.run")
    @mock.patch("setup._gh_target_repo", return_value="owner/repo")
    @mock.patch("setup.shutil.which", return_value="/usr/bin/gh")
    @mock.patch("builtins.input", side_effect=["y", ""])
    def test_github_offer_pushes_cookie_and_provider_keys(
        self, user_input, which, target_repo, run
    ):
        run.return_value = mock.Mock(returncode=0, stderr="")
        secrets = {name: f"value-for-{name}" for name in setup.SECRET_NAMES}

        setup.push_or_print_secrets(secrets)

        names = [call.args[0][3] for call in run.call_args_list]
        self.assertEqual(names, list(setup.SECRET_NAMES))
        for call in run.call_args_list:
            argv, name = call.args[0], call.args[0][3]
            self.assertNotIn(f"value-for-{name}", argv)
            self.assertEqual(call.kwargs["input"], f"value-for-{name}")


if __name__ == "__main__":
    unittest.main()

"""Lightweight bootstrap checks that run without third-party packages."""

import unittest

import manage


class BootstrapFilesTest(unittest.TestCase):
    def test_compose_configuration_exists(self) -> None:
        self.assertTrue((manage.ROOT / "docker-compose.yml").is_file())

    def test_line_endings_policy_exists(self) -> None:
        self.assertTrue((manage.ROOT / ".gitattributes").is_file())

    def test_expected_topics_are_declared(self) -> None:
        self.assertEqual(manage.TOPICS, ("transactions", "features", "scores", "alerts"))


if __name__ == "__main__":
    unittest.main()

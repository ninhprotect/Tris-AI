"""Tests for password policy and opaque local account sessions."""

import unittest

from auth import (
    Account,
    AccountError,
    AuthSessionManager,
    OAuthLoginCodeManager,
    PostgreSQLAccountStore,
    SocialOAuth,
)


class AuthTests(unittest.TestCase):
    def test_password_policy_rejects_weak_values(self) -> None:
        for password in ("short", "alllowercase123", "ALLUPPERCASE123", "NoDigitsHere"):
            with self.subTest(password=password):
                with self.assertRaises(AccountError):
                    PostgreSQLAccountStore._validate_password(password)

    def test_username_is_normalized_case_insensitively(self) -> None:
        display, key = PostgreSQLAccountStore._validate_username("Tan.Dep_Trai")
        self.assertEqual(display, "Tan.Dep_Trai")
        self.assertEqual(key, "tan.dep_trai")

    def test_session_token_is_opaque_and_revocable(self) -> None:
        manager = AuthSessionManager()
        account = Account("account-id", "tan", "Tan")
        token = manager.create(account)

        self.assertGreater(len(token), 40)
        self.assertNotIn("tan", token)
        self.assertEqual(manager.get(token), account)
        manager.revoke(token)
        self.assertIsNone(manager.get(token))

    def test_oauth_bridge_code_is_one_time_and_opaque(self) -> None:
        manager = OAuthLoginCodeManager()
        account = Account("account-id", "google_hash", "Tan", "google")
        code = manager.create("local-session-secret", account)

        self.assertNotIn("local-session-secret", code)
        self.assertEqual(manager.consume(code), ("local-session-secret", account))
        self.assertIsNone(manager.consume(code))

    def test_social_providers_are_disabled_without_credentials(self) -> None:
        providers = SocialOAuth().status()
        self.assertEqual(set(providers), {"google", "facebook"})
        self.assertIsInstance(providers["google"], bool)
        self.assertIsInstance(providers["facebook"], bool)


if __name__ == "__main__":
    unittest.main()

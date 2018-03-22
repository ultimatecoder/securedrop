# -*- coding: utf-8 -*-

import argparse
import logging
import os
import manage
import mock
import sys
import time

from StringIO import StringIO

os.environ['SECUREDROP_ENV'] = 'test'  # noqa

from models import Journalist


YUBIKEY_HOTP = ['cb a0 5f ad 41 a2 ff 4e eb 53 56 3a 1b f7 23 2e ce fc dc',
                'cb a0 5f ad 41 a2 ff 4e eb 53 56 3a 1b f7 23 2e ce fc dc d7']


class TestManagePy(object):

    def test_parse_args(self):
        # just test that the arg parser is stable
        manage.get_args()

    def test_not_verbose(self, caplog):
        args = manage.get_args().parse_args(['run'])
        manage.setup_verbosity(args)
        manage.log.debug('INVISIBLE')
        assert 'INVISIBLE' not in caplog.text

    def test_verbose(self, caplog):
        args = manage.get_args().parse_args(['--verbose', 'run'])
        manage.setup_verbosity(args)
        manage.log.debug('VISIBLE')
        assert 'VISIBLE' in caplog.text


class TestManagementCommand:

    def test_get_username_success(self):
        with mock.patch("__builtin__.raw_input", return_value='jen'):
            assert manage._get_username() == 'jen'

    def test_get_username_fail(self):
        bad_username = 'a' * (Journalist.MIN_USERNAME_LEN - 1)
        with mock.patch("__builtin__.raw_input",
                        side_effect=[bad_username, 'jen']):
            assert manage._get_username() == 'jen'

    def test_get_yubikey_usage_yes(self):
        with mock.patch("__builtin__.raw_input", return_value='y'):
            assert manage._get_yubikey_usage()

    def test_get_yubikey_usage_no(self):
        with mock.patch("__builtin__.raw_input", return_value='n'):
            assert not manage._get_yubikey_usage()

    # Note: we use the `journalist_app` fixture because it creates the DB
    def test_handle_invalid_secret(self, journalist_app, config, mocker):
        """Regression test for bad secret logic in manage.py"""

        mocker.patch("manage._get_username", return_value='ntoll'),
        mocker.patch("manage._get_yubikey_usage", return_value=True),
        mocker.patch("__builtin__.raw_input", side_effect=YUBIKEY_HOTP),
        mocker.patch("sys.stdout", new_callable=StringIO),

        original_config = manage.config

        try:
            # We need to override the config to point at the per-test DB
            manage.config = config

            # We will try to provide one invalid and one valid secret
            return_value = manage._add_user()

            assert return_value == 0
            assert 'Try again.' in sys.stdout.getvalue()
            assert 'successfully added' in sys.stdout.getvalue()
        finally:
            manage.config = original_config

    # Note: we use the `journalist_app` fixture because it creates the DB
    def test_exception_handling_when_duplicate_username(self,
                                                        journalist_app,
                                                        config,
                                                        mocker):
        """Regression test for duplicate username logic in manage.py"""

        mocker.patch("manage._get_username", return_value='foo-bar-baz')
        mocker.patch("manage._get_yubikey_usage", return_value=False)
        mocker.patch("sys.stdout", new_callable=StringIO)

        original_config = manage.config

        try:
            # We need to override the config to point at the per-test DB
            manage.config = config

            # Inserting the user for the first time should succeed
            return_value = manage._add_user()
            assert return_value == 0
            assert 'successfully added' in sys.stdout.getvalue()

            # Inserting the user for a second time should fail
            return_value = manage._add_user()
            assert return_value == 1
            assert ('ERROR: That username is already taken!' in
                    sys.stdout.getvalue())
        finally:
            manage.config = original_config

    # Note: we use the `journalist_app` fixture because it creates the DB
    def test_delete_user(self, journalist_app, config, mocker):
        mocker.patch("manage._get_username", return_value='test-user-56789')
        mocker.patch("manage._get_yubikey_usage", return_value=False)
        mocker.patch("manage._get_username_to_delete",
                     return_value='test-user-56789')
        mocker.patch('manage._get_delete_confirmation', return_value=True)

        original_config = manage.config

        try:
            # We need to override the config to point at the per-test DB
            manage.config = config

            return_value = manage._add_user()
            assert return_value == 0

            return_value = manage.delete_user(args=None)
            assert return_value == 0
        finally:
            manage.config = original_config

    # Note: we use the `journalist_app` fixture because it creates the DB
    def test_delete_non_existent_user(self, journalist_app, config, mocker):
        mocker.patch("manage._get_username_to_delete",
                     return_value='does-not-exist')
        mocker.patch('manage._get_delete_confirmation', return_value=True)
        mocker.patch("sys.stdout", new_callable=StringIO)

        original_config = manage.config

        try:
            # We need to override the config to point at the per-test DB
            manage.config = config
            return_value = manage.delete_user(args=None)
            assert return_value == 0
            assert 'ERROR: That user was not found!' in sys.stdout.getvalue()
        finally:
            manage.config = original_config

    def test_get_username_to_delete(self, mocker):
        mocker.patch("__builtin__.raw_input", return_value='test-user-12345')
        return_value = manage._get_username_to_delete()
        assert return_value == 'test-user-12345'

    def test_reset(self, journalist_app, test_journo, config):
        original_config = manage.config
        try:
            # We need to override the config to point at the per-test DB
            manage.config = config

            return_value = manage.reset(args=None)
            assert return_value == 0
            assert os.path.exists(config.DATABASE_FILE)
            assert os.path.exists(config.STORE_DIR)

            # Verify journalist user present in the database is gone
            with journalist_app.app_context():
                res = Journalist.query \
                    .filter_by(username=test_journo['username']).one_or_none()
                assert res is None
        finally:
            manage.config = original_config

    def test_get_username(self, mocker):
        mocker.patch("__builtin__.raw_input", return_value='foo-bar-baz')
        assert manage._get_username() == 'foo-bar-baz'

    def test_clean_tmp_do_nothing(self, caplog):
        args = argparse.Namespace(days=0,
                                  directory=' UNLIKELY::::::::::::::::: ',
                                  verbose=logging.DEBUG)
        manage.setup_verbosity(args)
        manage.clean_tmp(args)
        assert 'does not exist, do nothing' in caplog.text

    def test_clean_tmp_too_young(self, config, caplog):
        args = argparse.Namespace(days=24*60*60,
                                  directory=config.TEMP_DIR,
                                  verbose=logging.DEBUG)
        # create a file
        open(os.path.join(config.TEMP_DIR, 'FILE'), 'a').close()

        manage.setup_verbosity(args)
        manage.clean_tmp(args)
        assert 'modified less than' in caplog.text

    def test_clean_tmp_removed(self, config, caplog):
        args = argparse.Namespace(days=0,
                                  directory=config.TEMP_DIR,
                                  verbose=logging.DEBUG)
        fname = os.path.join(config.TEMP_DIR, 'FILE')
        with open(fname, 'a'):
            old = time.time() - 24*60*60
            os.utime(fname, (old, old))
        manage.setup_verbosity(args)
        manage.clean_tmp(args)
        assert 'FILE removed' in caplog.text

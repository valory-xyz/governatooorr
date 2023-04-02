# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Test the handlers.py module of the DynamicNFT skill."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, cast
from unittest.mock import patch

import pytest
from aea.protocols.dialogue.base import DialogueMessage
from aea.test_tools.test_skill import BaseSkillTestCase

from packages.fetchai.connections.http_server.connection import (
    PUBLIC_ID as HTTP_SERVER_PUBLIC_ID,
)
from packages.valory.protocols.http.message import HttpMessage
from packages.valory.skills.proposal_collector_abci.dialogues import HttpDialogues
from packages.valory.skills.proposal_collector_abci.handlers import HttpHandler


PACKAGE_DIR = Path(__file__).parent.parent

HTTP_SERVER_SENDER = str(HTTP_SERVER_PUBLIC_ID.without_hash())

URL_BASE = "https://governatooorr.staging.autonolas.tech/"


@dataclass
class HandlerTestCase:
    """HandlerTestCase"""

    name: str
    request_url: str
    request_body: bytes
    token_to_data: Dict[str, str]
    response_status_code: int
    response_status_text: str
    response_headers: str
    response_body: bytes
    method: str
    n_outbox_msgs: int
    set_last_update_time: bool = True


class TestHttpHandler(BaseSkillTestCase):
    """Test HttpHandler of http_echo."""

    path_to_skill = PACKAGE_DIR

    @classmethod
    def setup_class(cls):
        """Setup the test class."""
        super().setup_class()
        cls.http_handler = cast(HttpHandler, cls._skill.skill_context.handlers.http)
        cls.logger = cls._skill.skill_context.logger

        cls.http_dialogues = cast(
            HttpDialogues, cls._skill.skill_context.http_dialogues
        )

        cls.get_method = "get"
        cls.post_method = "post"
        cls.url = f"{URL_BASE}"
        cls.version = "some_version"
        cls.headers = "some_headers"
        cls.body = b"some_body/"
        cls.sender = HTTP_SERVER_SENDER
        cls.skill_id = str(cls._skill.skill_context.skill_id)

        cls.status_code = 100
        cls.status_text = "some_status_text"

        cls.content = b"some_content"
        cls.list_of_messages = (
            DialogueMessage(
                HttpMessage.Performative.REQUEST,
                {
                    "method": cls.get_method,
                    "url": cls.url,
                    "version": cls.version,
                    "headers": cls.headers,
                    "body": cls.body,
                },
            ),
        )

    def setup(self) -> None:
        """Setup"""
        self.http_handler.setup()

    def test_setup(self):
        """Test the setup method of the handler."""
        assert self.http_handler.setup() is None
        self.assert_quantity_in_outbox(0)

    def test_handle_unidentified_dialogue(self):
        """Test the _handle_unidentified_dialogue method of the handler."""
        # setup
        incorrect_dialogue_reference = ("", "")
        incoming_message = self.build_incoming_message(
            message_type=HttpMessage,
            dialogue_reference=incorrect_dialogue_reference,
            performative=HttpMessage.Performative.REQUEST,
            to=self.skill_id,
            method=self.get_method,
            url=self.url,
            version=self.version,
            headers=self.headers,
            body=self.body,
            sender=HTTP_SERVER_SENDER,
        )

        # operation
        with patch.object(self.logger, "log") as mock_logger:
            self.http_handler.handle(incoming_message)

        # after
        mock_logger.assert_any_call(
            logging.INFO,
            f"Received invalid http message={incoming_message}, unidentified dialogue.",
        )

    def test_teardown(self):
        """Test the teardown method of the handler."""
        assert self.http_handler.teardown() is None
        self.assert_quantity_in_outbox(0)

    @pytest.mark.parametrize(
        "url, method, expected_handler_name",
        [
            ("wrong_url", "get", None),
            (
                "http://governatooorr.staging.autonolas.tech/dummy",
                "get",
                "_handle_bad_request",
            ),
            (
                "http://governatooorr.staging.autonolas.tech/delegate",
                "post",
                "_handle_post_delegate",
            ),
            (
                "http://governatooorr.staging.autonolas.tech/delegations/0x0000000000000000000000000000000000000000",
                "get",
                "_handle_get_delegations",
            ),
            (
                "http://governatooorr.staging.autonolas.tech/proposals",
                "get",
                "_handle_get_proposals",
            ),
            (
                "http://governatooorr.staging.autonolas.tech/proposal/1",
                "get",
                "_handle_get_proposal",
            ),
            (
                "http://governatooorr.staging.autonolas.tech/proposal/1d",
                "get",
                "_handle_bad_request",
            ),
        ],
    )
    def test_get_handler(self, url, method, expected_handler_name):
        """Test check_url"""
        expected_handler = (
            getattr(self.http_handler, expected_handler_name)
            if expected_handler_name
            else None
        )
        actual_handler, _ = self.http_handler._get_handler(url, method)
        assert (
            actual_handler == expected_handler
        ), f"Wrong value for {url}. Expected {expected_handler}, got {actual_handler}"

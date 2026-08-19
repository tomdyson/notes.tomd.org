import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest import TestCase, mock


SCRIPT_PATH = (
    Path(__file__).parents[2] / "skills" / "share-notes" / "scripts" / "share_note.py"
)
SPEC = importlib.util.spec_from_file_location("share_note_skill", SCRIPT_PATH)
share_note = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(share_note)


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.body


class ShareNoteScriptTests(TestCase):
    def test_publish_sends_bearer_token_and_idempotency_key(self):
        result_body = {"url": "https://notes.tomd.org/abc123/"}
        with mock.patch.object(
            share_note, "urlopen", return_value=FakeResponse(result_body)
        ) as urlopen:
            result = share_note.publish(
                api_url="https://notes.tomd.org/api/v1/notes",
                token="nt_secret",
                payload={"markdown": "hello"},
                idempotency_key="request-1",
                timeout=10,
            )

        self.assertEqual(result, result_body)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer nt_secret")
        self.assertEqual(request.get_header("Idempotency-key"), "request-1")
        self.assertEqual(json.loads(request.data), {"markdown": "hello"})

    def test_main_reads_markdown_file_and_prints_result(self):
        with NamedTemporaryFile(mode="w", suffix=".md", encoding="utf-8") as source:
            source.write("# Shared")
            source.flush()
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"NOTES_TOMD_TOKEN": "nt_secret"}),
                mock.patch.object(
                    share_note,
                    "publish",
                    return_value={"url": "https://notes.tomd.org/abc123/"},
                ) as publish,
                mock.patch.object(sys, "stdout", stdout),
            ):
                share_note.main([source.name, "--title", "Shared note"])

        self.assertEqual(
            publish.call_args.kwargs["payload"],
            {"markdown": "# Shared", "title": "Shared note"},
        )
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {"url": "https://notes.tomd.org/abc123/"},
        )

    def test_main_requires_token_without_echoing_one(self):
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(share_note.ShareNoteError, "NOTES_TOMD_TOKEN"),
        ):
            share_note.main([])

    def test_password_is_read_from_named_environment_variable(self):
        stdin = io.StringIO("secret note")
        with (
            mock.patch.dict(
                os.environ,
                {
                    "NOTES_TOMD_TOKEN": "nt_secret",
                    "NOTE_PASSWORD": "note-secret",
                },
                clear=True,
            ),
            mock.patch.object(sys, "stdin", stdin),
            mock.patch.object(sys, "stdout", io.StringIO()),
            mock.patch.object(
                share_note, "publish", return_value={"url": "https://example.test/n/"}
            ) as publish,
        ):
            share_note.main(["--password-env", "NOTE_PASSWORD"])

        self.assertEqual(publish.call_args.kwargs["payload"]["password"], "note-secret")

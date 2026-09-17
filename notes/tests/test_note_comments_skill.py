import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest import TestCase, mock


SCRIPTS = Path(__file__).parents[2] / "skills" / "share-notes" / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_skill", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


share_note = load("share_note")
note_comments = load("note_comments")
TOKEN_ENV = {"NOTES_TOMD_TOKEN": "nt_secret"}


class FakeResponse:
    def __init__(self, raw):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.raw


class ApiRequestTests(TestCase):
    def test_get_sends_token_without_a_body(self):
        with mock.patch.object(
            share_note, "urlopen", return_value=FakeResponse(b'{"comments": []}')
        ) as urlopen:
            result = share_note.api_request(
                "GET", "https://notes.tomd.org/api/v1/notes/abc/comments", token="nt_secret", timeout=5
            )
        request = urlopen.call_args.args[0]
        self.assertEqual(result, {"comments": []})
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertEqual(request.get_header("Authorization"), "Bearer nt_secret")
        self.assertIsNone(request.get_header("Idempotency-key"))

    def test_empty_response_body_is_an_empty_result(self):
        with mock.patch.object(share_note, "urlopen", return_value=FakeResponse(b"")):
            result = share_note.api_request(
                "DELETE", "https://notes.tomd.org/api/v1/notes/abc/comments/7", token="nt_secret", timeout=5
            )
        self.assertEqual(result, {})


class ShareNoteCommentsFlagTests(TestCase):
    def run_main(self, argv):
        with (
            mock.patch.dict(os.environ, TOKEN_ENV, clear=True),
            mock.patch.object(sys, "stdin", io.StringIO("# note")),
            mock.patch.object(sys, "stdout", io.StringIO()),
            mock.patch.object(share_note, "publish", return_value={"url": "x"}) as publish,
        ):
            share_note.main(argv)
        return publish.call_args.kwargs["payload"]

    def test_comments_flag_enables_comments(self):
        self.assertIs(self.run_main(["--comments"])["comments_enabled"], True)

    def test_comments_are_not_mentioned_by_default(self):
        self.assertNotIn("comments_enabled", self.run_main([]))


class SlugTests(TestCase):
    def test_accepts_slug_or_note_url(self):
        for value in (
            "abc123",
            "https://notes.tomd.org/abc123/",
            "https://notes.tomd.org/abc123",
            "https://notes.tomd.org/abc123/#comment-4",
            "https://notes.tomd.org/abc123/edit/",
        ):
            self.assertEqual(note_comments.slug_from(value), "abc123", value)

    def test_rejects_things_that_are_not_a_slug(self):
        for value in ("", "../etc", "a b", "https://notes.tomd.org/"):
            with self.assertRaises(note_comments.ShareNoteError, msg=value):
                note_comments.slug_from(value)

    def test_comments_url_is_built_from_the_notes_api_url(self):
        self.assertEqual(
            note_comments.comments_url("https://notes.tomd.org/api/v1/notes/", "abc123"),
            "https://notes.tomd.org/api/v1/notes/abc123/comments",
        )


class NoteCommentsMainTests(TestCase):
    def run_main(self, argv, *, result=None, stdin="", env=TOKEN_ENV):
        stdout = io.StringIO()
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(sys, "stdin", io.StringIO(stdin)),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(note_comments, "api_request", return_value=result or {}) as api_request,
        ):
            note_comments.main(argv)
        return api_request, stdout.getvalue()

    def test_list_gets_the_thread_and_prints_it(self):
        api_request, out = self.run_main(
            ["list", "https://notes.tomd.org/abc123/"], result={"comments": [{"id": 1}]}
        )
        self.assertEqual(api_request.call_args.args[:2],
                         ("GET", "https://notes.tomd.org/api/v1/notes/abc123/comments"))
        self.assertEqual(api_request.call_args.kwargs["token"], "nt_secret")
        self.assertEqual(json.loads(out), {"comments": [{"id": 1}]})

    def test_add_posts_body_from_stdin_with_an_idempotency_key(self):
        api_request, _ = self.run_main(["add", "abc123"], stdin="Looks good to me.\n")
        self.assertEqual(api_request.call_args.args[:2],
                         ("POST", "https://notes.tomd.org/api/v1/notes/abc123/comments"))
        self.assertEqual(api_request.call_args.kwargs["payload"], {"body": "Looks good to me.\n"})
        self.assertTrue(api_request.call_args.kwargs["idempotency_key"])

    def test_add_reads_a_file_and_anchors_to_a_quote(self):
        with NamedTemporaryFile(mode="w", suffix=".txt", encoding="utf-8") as source:
            source.write("Typo here")
            source.flush()
            api_request, _ = self.run_main(
                ["add", "abc123", source.name, "--quote", "text to", "--prefix", "Some ",
                 "--suffix", " discuss.", "--author-name", "Tom (via Claude)"]
            )
        self.assertEqual(
            api_request.call_args.kwargs["payload"],
            {"body": "Typo here", "quote": "text to", "prefix": "Some ",
             "suffix": " discuss.", "author_name": "Tom (via Claude)"},
        )

    def test_reply_sets_parent(self):
        api_request, _ = self.run_main(["add", "abc123", "--reply-to", "7"], stdin="Fixed.")
        self.assertEqual(api_request.call_args.kwargs["payload"], {"body": "Fixed.", "parent": 7})

    def test_reply_cannot_also_carry_a_quote(self):
        with self.assertRaisesRegex(note_comments.ShareNoteError, "repl"):
            self.run_main(["add", "abc123", "--reply-to", "7", "--quote", "x"], stdin="Fixed.")

    def test_empty_comment_is_refused_before_any_request(self):
        with self.assertRaisesRegex(note_comments.ShareNoteError, "empty"):
            self.run_main(["add", "abc123"], stdin="  \n")

    def test_delete_targets_one_comment(self):
        api_request, out = self.run_main(["delete", "abc123", "7"])
        self.assertEqual(api_request.call_args.args[:2],
                         ("DELETE", "https://notes.tomd.org/api/v1/notes/abc123/comments/7"))
        self.assertEqual(json.loads(out), {"deleted": 7, "slug": "abc123"})

    def test_api_url_override_from_environment(self):
        api_request, _ = self.run_main(
            ["list", "abc123"], env={**TOKEN_ENV, "NOTES_TOMD_API_URL": "http://localhost:8765/api/v1/notes"}
        )
        self.assertEqual(api_request.call_args.args[1], "http://localhost:8765/api/v1/notes/abc123/comments")

    def test_requires_token_without_echoing_one(self):
        with self.assertRaisesRegex(note_comments.ShareNoteError, "NOTES_TOMD_TOKEN"):
            self.run_main(["list", "abc123"], env={})

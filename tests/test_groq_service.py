import json
import unittest
from unittest import mock

from voiceover2video.models import Scene
from voiceover2video.services.groq_service import generate_scenes, generate_scenes_from_chunks, target_scene_count


class FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.last_kwargs: dict = {}

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        completion = type("Completion", (), {})()
        choice = type("Choice", (), {})()
        message = type("Message", (), {})()
        message.content = self.content
        choice.message = message
        completion.choices = [choice]
        return completion


class FakeTranscriptions:
    def create(self, **kwargs):
        result = type("Result", (), {})()
        result.text = "fake transcribed chunk text"
        result.segments = []
        return result


class FakeClient:
    def __init__(self, content: str = "{}"):
        self.chat = type("Chat", (), {"completions": FakeCompletions(content)})()
        self.audio = type("Audio", (), {"transcriptions": FakeTranscriptions()})()


class TestGroqService(unittest.TestCase):
    def test_parses_scene_breakdown(self):
        payload = {
            "scenes": [
                {"narration": "The lion roared loudly.", "keywords": ["lion", "savanna"]},
                {"narration": "The sun set slowly.", "keywords": ["sunset", "sky"]},
            ]
        }
        client = FakeClient(json.dumps(payload))
        scenes = generate_scenes(client=client, story="A lion roared. The sun set.", model="test-model")
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0].narration, "The lion roared loudly.")
        self.assertEqual(scenes[0].keywords, ["lion", "savanna"])
        self.assertGreater(scenes[0].duration, 0)

    def test_empty_breakdown_raises(self):
        client = FakeClient(json.dumps({"scenes": []}))
        with self.assertRaises(ValueError):
            generate_scenes(client=client, story="tiny", model="test-model")

    def test_scene_count_scales_with_duration(self):
        self.assertEqual(target_scene_count(0), 3)
        self.assertEqual(target_scene_count(30), 5)
        self.assertEqual(target_scene_count(120), 20)
        self.assertEqual(target_scene_count(10_000), 40)

    def test_default_prompt_uses_three_to_eight_scenes(self):
        client = FakeClient(json.dumps({"scenes": [{"narration": "Hi.", "keywords": ["hi"]}]}))
        generate_scenes(client=client, story="A story.", model="test-model")
        prompt = client.chat.completions.last_kwargs["messages"][-1]["content"]
        self.assertIn("3 to 8 consecutive scenes", prompt)
        self.assertEqual(client.chat.completions.last_kwargs["max_tokens"], 2048)

    def test_explicit_scene_count_drives_prompt_and_token_budget(self):
        client = FakeClient(json.dumps({"scenes": [{"narration": "Hi.", "keywords": ["hi"]}]}))
        generate_scenes(client=client, story="A story.", model="test-model", scene_count=40)
        kwargs = client.chat.completions.last_kwargs
        self.assertIn("exactly 40 consecutive scenes", kwargs["messages"][-1]["content"])
        self.assertEqual(kwargs["max_tokens"], 3200)

    def test_generate_scenes_from_chunks_builds_one_scene_per_chunk(self):
        with mock.patch("voiceover2video.services.groq_service.split_audio", return_value=["/tmp/opencode/chunk_000.mp3", "/tmp/opencode/chunk_001.mp3"]), mock.patch(
            "voiceover2video.services.groq_service.transcribe_audio", return_value={"text": "fake transcribed chunk text", "segments": []}
        ) as transcribe_mock, mock.patch(
            "voiceover2video.services.groq_service.generate_scenes", return_value=[Scene(index=0, narration="Fake chunk narration.", keywords=["fake", "chunk"], duration=3.0)]
        ) as generate_mock:
            scenes = generate_scenes_from_chunks(
                client=FakeClient(),
                audio_path="narration.mp3",
                model="test-model",
                chunk_seconds=3.0,
                scene_count=2,
                chat_model="test-chat-model",
            )
        self.assertEqual(len(scenes), 2)
        self.assertEqual(scenes[0].narration, "fake transcribed chunk text")
        self.assertEqual(scenes[1].narration, "fake transcribed chunk text")
        self.assertEqual(scenes[0].keywords, ["fake", "chunk"])
        self.assertEqual(scenes[0].duration, 3.0)
        self.assertEqual(scenes[1].duration, 3.0)
        self.assertEqual(transcribe_mock.call_count, 2)
        self.assertEqual(generate_mock.call_count, 2)

    def test_single_scene_prompt_asks_for_single_keyword(self):
        client = FakeClient(json.dumps({"scenes": [{"narration": "Hi.", "keywords": ["hi"]}]}))
        generate_scenes(client=client, story="A story.", model="test-model", scene_count=1)
        prompt = client.chat.completions.last_kwargs["messages"][-1]["content"]
        self.assertIn("Split the story into exactly 1 consecutive scenes", prompt)
        self.assertIn("a single short lowercase English keyword", prompt)


if __name__ == "__main__":
    unittest.main()

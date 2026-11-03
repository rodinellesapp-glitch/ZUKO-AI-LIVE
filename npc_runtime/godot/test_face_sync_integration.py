"""Offline structural checks for the reversible Presenter V4 face overlay."""
from pathlib import Path
import unittest

ROOT = Path(__file__).parent


class FaceSyncIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene = (ROOT / "Main.tscn").read_text(encoding="utf-8")
        cls.main = (ROOT / "Main.gd").read_text(encoding="utf-8")
        cls.face = (ROOT / "FaceSync.gd").read_text(encoding="utf-8")
        cls.bridge = (ROOT.parent.parent / "live_social_01" / "npc_panel_bridge.py").read_text(encoding="utf-8")

    def test_overlay_is_a_separate_enabled_scene_node(self):
        self.assertIn('path="res://FaceSync.gd" type="Script" id=4', self.scene)
        self.assertIn('[node name="FaceSync" type="Node" parent="."]', self.scene)
        self.assertIn("enabled = true", self.scene)

    def test_original_character_is_attached_without_mesh_replacement(self):
        self.assertIn('const CHARACTER_SCENE = "res://assets/character/Character.gltf"', self.main)
        self.assertIn("$CharacterAnchor.add_child(character)", self.main)
        self.assertIn("face_sync.attach(character)", self.main)
        self.assertIn('attachment.bone_name = "Head"', self.face)
        self.assertIn('nose.name = "FaceSyncNose"', self.face)
        self.assertIn('mouth.name = "FaceSyncMouth"', self.face)

    def test_face_state_follows_only_existing_speech_state(self):
        self.assertIn("face_sync.set_speaking(true)", self.main)
        self.assertIn("face_sync.set_speaking(false)", self.main)
        self.assertLess(self.main.index("face_sync.set_speaking(true)"), self.main.index("if manual_override or manually_paused:"))
        self.assertIn("self._queue_movement_confirmation(sent_speech_correlation,'SPEECH',gesture)", self.bridge)
        self.assertNotIn("if gesture != 'Idle':", self.bridge)
        self.assertIn("if self.state=='ACTIVE' and self.speech != sent_speech:", self.bridge)
        self.assertIn("if sent_speech:", self.bridge)
        self.assertIn("gesture = self.speech_animation if self.auto_movements_enabled and not self.manual_override and not self.manual_paused and not self.external_paused else 'Idle'", self.bridge)
        self.assertIn("_set_speech_active(true)", self.main)
        self.assertIn("_set_speech_active(false)", self.main)
        self.assertIn('if key == "idle" and payload.get("speech_end", false) == true:', self.main)

    def test_speech_is_smoothed_and_closes_when_inactive(self):
        self.assertIn("mouth_value = lerp(mouth_value, target, 1.0 - exp(-delta * 15.0))", self.face)
        self.assertIn("if speaking:", self.face)
        self.assertIn("speaking = bool(active) and enabled and attached", self.face)
        self.assertIn("enabled = true", self.scene)

    def test_rms_limitation_is_identified(self):
        self.assertIn("rms=unavailable", self.face)
        self.assertIn("TTS callbacks expose", self.face)


if __name__ == "__main__":
    unittest.main(verbosity=2)
extends "res://Main.gd"

# Only presentation state. Rig, original animations and speech pipeline stay in Main.gd.
var walking_active = false
var live_mode = false
var background_speed = 1.0
var render_resolution = "540x960"
var status_enabled = false
var depth_stage = null
var dev_window_size = Vector2(600, 900)
const LIVE_SIZES = {"540x960": Vector2(540, 960), "720x1280": Vector2(720, 1280), "1080x1920": Vector2(1080, 1920)}
const LOCOMOTION_ANIMATIONS = ["Walk", "Walk_Gun", "Run", "Run_Gun", "Run_Shoot", "WalkWave", "WalkYes", "WalkNo"]
const AUTO_ANIMATIONS = ["Idle", "Jump", "No", "Walk", "WalkWave", "Wave", "Yes"]
const WALK_WAVE_ANIMATION = "WalkWave"
const WALK_COMBO_NAMES = {"Wave": "WalkWave", "Yes": "WalkYes", "No": "WalkNo"}
const WALK_COMBO_GESTURES = ["Wave", "Yes", "No"]
const RUN_SPEED_FACTOR = 1.45
var automatic_movements_enabled = false
var automatic_walking = false
var walk_wave_enabled = false
var walk_wave_available = false
var walk_wave_error = ""
var walk_combo_enabled = {"Wave": false, "Yes": false, "No": false}
var walk_combo_available = {"Wave": false, "Yes": false, "No": false}
var walk_combo_bones = {}
var walk_combo_tracks = {}
var walk_combo_errors = {}
var scenery_moving = false
var animation_source = "GODOT"
var preferred_locomotion = "Walk"
var manual_override_before_pause = false

func _ready():
	dev_window_size = OS.window_size
	_prepare_walk_wave()
	_prepare_walk_combos()
	depth_stage = load("res://PaulistaDepth.gd").new()
	depth_stage.name = "PaulistaDepth"
	add_child(depth_stage)
	# Godot 3 invokes inherited _ready automatically before this method.

func _prepare_walk_wave():
	if animation_player == null:
		walk_wave_error = "ANIMATION_PLAYER"
		push_error("WALK_WAVE_BUILD_FAILED reason=" + walk_wave_error)
		return
	var builder = load("res://WalkWaveCandidate.gd")
	if builder == null:
		walk_wave_error = "BUILDER_LOAD"
		push_error("WALK_WAVE_BUILD_FAILED reason=" + walk_wave_error)
		return
	var candidate = builder.build(animation_player)
	if candidate == null:
		walk_wave_error = "CANDIDATE_BUILD"
		push_error("WALK_WAVE_BUILD_FAILED reason=" + walk_wave_error)
		return
	candidate.loop = true
	animation_player.add_animation(WALK_WAVE_ANIMATION, candidate)
	walk_wave_available = true
	walk_combo_available["Wave"] = true
	var combo_builder = load("res://WalkComboBuilder.gd")
	if combo_builder != null:
		var details = combo_builder.build(animation_player, "Wave")
		if details != null:
			walk_combo_bones["Wave"] = details.bones
			walk_combo_tracks["Wave"] = details.tracks
	print("WALK_WAVE_READY tracks=" + str(candidate.get_track_count()) + " enabled=false")

func _prepare_walk_combos():
	var builder = load("res://WalkComboBuilder.gd")
	if builder == null:
		for gesture in ["Yes", "No"]:
			walk_combo_errors[gesture] = "BUILDER_LOAD"
		return
	for gesture in ["Yes", "No"]:
		var result = builder.build(animation_player, gesture)
		var candidate_name = WALK_COMBO_NAMES[gesture]
		if result == null:
			walk_combo_errors[gesture] = "CANDIDATE_BUILD"
			push_error("WALK_COMBO_BUILD_FAILED gesture=" + gesture + " reason=" + walk_combo_errors[gesture])
			continue
		animation_player.add_animation(candidate_name, result.animation)
		walk_combo_available[gesture] = true
		walk_combo_bones[gesture] = result.bones
		walk_combo_tracks[gesture] = result.tracks
		print("WALK_COMBO_READY gesture=" + gesture + " animation=" + candidate_name + " tracks=" + str(result.count) + " bones=" + ",".join(result.bones))

func _process(delta):
	var moving = walking_active and current_animation in LOCOMOTION_ANIMATIONS and not manually_paused
	scenery_moving = moving
	var speed_factor = RUN_SPEED_FACTOR if current_animation in ["Run", "Run_Gun", "Run_Shoot"] else 1.0
	if animation_player != null:
		# Couple the animation cadence and the existing depth stage only to locomotion.
		animation_player.playback_speed = background_speed * speed_factor if moving else 1.0
	if depth_stage != null:
		depth_stage.advance(delta, moving, min(2.5, background_speed * speed_factor))

func handle_event(event_data):
	# An explicit legacy Idle stops walking; speech_end only ends a speech gesture.
	if typeof(event_data) == TYPE_STRING and event_data == "idle":
		walking_active = false
	if typeof(event_data) == TYPE_DICTIONARY and event_data.get("event", "") == "idle" and not event_data.get("speech_end", false):
		walking_active = false
	var result = .handle_event(event_data)
	_publish_status()
	return result

func _handle_control(payload):
	var command = payload.get("command", "")
	if command == "walk_wave_mode":
		if payload.size() != 2 or typeof(payload.get("enabled")) != TYPE_BOOL:
			return false
		if payload.enabled and not walk_wave_available:
			walk_wave_error = "CANDIDATE_UNAVAILABLE"
			push_error("WALK_WAVE_MODE_REJECTED reason=" + walk_wave_error)
			_publish_status()
			return false
		walk_wave_enabled = payload.enabled
		walk_combo_enabled["Wave"] = payload.enabled
		if walking_active and animation_source == "AUTOMÁTICO" and not is_reacting:
			preferred_locomotion = WALK_WAVE_ANIMATION if walk_wave_enabled else "Walk"
			_play_idle()
		print("WALK_WAVE_MODE enabled=" + str(walk_wave_enabled))
		_publish_status()
		return true
	if command == "walk_combo_mode":
		var gesture = payload.get("animation", "")
		if payload.size() != 3 or not gesture in ["Yes", "No"] or typeof(payload.get("enabled")) != TYPE_BOOL:
			return false
		if payload.enabled and not walk_combo_available.get(gesture, false):
			walk_combo_errors[gesture] = "CANDIDATE_UNAVAILABLE"
			push_error("WALK_COMBO_MODE_REJECTED gesture=" + gesture + " reason=" + walk_combo_errors[gesture])
			_publish_status()
			return false
		walk_combo_enabled[gesture] = payload.enabled
		print("WALK_COMBO_MODE gesture=" + gesture + " enabled=" + str(payload.enabled))
		_publish_status()
		return true
	if command == "auto_mode":
		if payload.size() != 2 or typeof(payload.get("enabled")) != TYPE_BOOL:
			return false
		automatic_movements_enabled = payload.enabled
		if not automatic_movements_enabled:
			if automatic_walking:
				automatic_walking = false
				walking_active = false
			if not manual_override and animation_source == "AUTOMÁTICO":
				if animation_player != null and is_reacting:
					animation_player.stop()
				is_reacting = false
				speech_active = false
				speech_gesture_pending = false
				speech_gesture_running = false
				event_queue.clear()
				_play_idle()
				animation_source = "MANUAL" if walking_active else "GODOT"
		_publish_status()
		return true
	if command == "auto_animate":
		var clip = payload.get("animation", "")
		if payload.size() != 2 or not automatic_movements_enabled or manual_override or manually_paused:
			return false
		if typeof(clip) != TYPE_STRING or not clip in AUTO_ANIMATIONS or animation_player == null or not animation_player.has_animation(clip):
			return false
		if clip in ["Walk", WALK_WAVE_ANIMATION]:
			if clip == WALK_WAVE_ANIMATION and (not walk_wave_enabled or not walk_wave_available):
				walk_wave_error = "CANDIDATE_DISABLED_OR_UNAVAILABLE"
				push_error("WALK_WAVE_AUTO_REJECTED reason=" + walk_wave_error)
				_publish_status()
				return false
			automatic_walking = true
			walking_active = true
			preferred_locomotion = WALK_WAVE_ANIMATION if clip == WALK_WAVE_ANIMATION else (WALK_WAVE_ANIMATION if walk_wave_enabled and walk_wave_available else "Walk")
			animation_source = "AUTOMÁTICO"
			_play_idle()
			_publish_status()
			return true
		if clip in WALK_COMBO_GESTURES and walking_active and _walk_combo_is_enabled(clip):
			if _play_walk_combo(clip, "AUTOMÁTICO", false):
				return true
		if clip == "Idle":
			if not automatic_walking:
				return false
			automatic_walking = false
			walking_active = false
			animation_source = "AUTOMÁTICO"
			_play_idle()
			_publish_status()
			return true
		if is_reacting:
			return false
		animation_source = "AUTOMÁTICO"
		_play_reaction(clip, "Movimento automático")
		return true
	if command == "animate":
		var manual_clip = payload.get("animation", "")
		if manual_clip in LOCOMOTION_ANIMATIONS:
			if manually_paused or animation_player == null or not animation_player.has_animation(manual_clip):
				return false
			walking_active = true
			automatic_walking = false
			preferred_locomotion = manual_clip
			animation_source = "MANUAL"
			var looping_payload = payload.duplicate(true)
			looping_payload["repeat"] = true
			var movement_result = ._handle_control(looping_payload)
			_publish_status()
			return movement_result
		if manual_clip in WALK_COMBO_GESTURES and walking_active and _walk_combo_is_enabled(manual_clip):
			if _play_walk_combo(manual_clip, "MANUAL", true):
				return true
	if payload.get("command", "") == "presentation":
		return _handle_presentation(payload)
	if manually_paused and command == "animate":
		return false
	var was_walking = walking_active
	if command == "pause":
		manual_override_before_pause = manual_override
	if command in ["idle", "stop"]:
		walking_active = false
		automatic_walking = false
	if command == "animate":
		var repeat = payload.get("repeat", false)
		if typeof(repeat) != TYPE_BOOL:
			return false
		if repeat or payload.get("animation", "") == "Idle":
			walking_active = false
			automatic_walking = false
	var result = ._handle_control(payload)
	if not result:
		walking_active = was_walking
	elif command == "animate":
		animation_source = "MANUAL"
	elif command in ["idle", "stop", "pause"]:
		animation_source = "MANUAL"
	elif command == "resume":
		manual_override = manual_override_before_pause
		animation_source = "MANUAL" if manual_override else "AUTOMÁTICO" if automatic_movements_enabled else "GODOT"
	_publish_status()
	return result

func _handle_presentation(payload):
	for key in payload.keys():
		if not key in ["command", "walking", "speed", "live", "resolution"]:
			return false
	for key in ["walking", "live"]:
		if payload.has(key) and typeof(payload[key]) != TYPE_BOOL:
			return false
	if payload.has("speed"):
		if not typeof(payload["speed"]) in [TYPE_INT, TYPE_REAL]:
			return false
		if payload["speed"] < 0.25 or payload["speed"] > 2.0:
			return false
	if payload.has("resolution") and not LIVE_SIZES.has(payload["resolution"]):
		return false
	if payload.get("walking", false) and manually_paused:
		return false
	status_enabled = true
	background_speed = float(payload.get("speed", background_speed))
	var next_resolution = payload.get("resolution", render_resolution)
	var next_live = payload.get("live", live_mode)
	if next_live != live_mode or next_resolution != render_resolution:
		render_resolution = next_resolution
		_set_live_mode(next_live)
	if payload.has("walking"):
		var next_walking = payload["walking"]
		if next_walking != walking_active:
			walking_active = next_walking
			automatic_walking = false
			preferred_locomotion = "Walk"
			animation_source = "MANUAL"
			manual_override = false
			manually_paused = false
			speech_active = false
			speech_gesture_pending = false
			speech_gesture_running = false
			event_queue.clear()
			_play_idle()
	_publish_status()
	return true

func _set_live_mode(enabled):
	live_mode = enabled
	$HUD/Panel.visible = not live_mode
	if live_mode:
		var size = LIVE_SIZES[render_resolution]
		get_tree().set_screen_stretch(SceneTree.STRETCH_MODE_VIEWPORT, SceneTree.STRETCH_ASPECT_KEEP, size)
		var screen = OS.get_screen_size()
		var display_height = min(960.0, screen.y - 100.0)
		OS.window_size = Vector2(round(display_height * 9.0 / 16.0), display_height)
	else:
		get_tree().set_screen_stretch(SceneTree.STRETCH_MODE_DISABLED, SceneTree.STRETCH_ASPECT_IGNORE, Vector2(600, 900))
		OS.window_size = dev_window_size

func _play_idle():
	if walking_active and not manually_paused and animation_player != null:
		if not animation_player.has_animation(preferred_locomotion):
			preferred_locomotion = "Walk"
		is_reacting = false
		current_animation = preferred_locomotion
		animation_player.get_animation(current_animation).loop = true
		animation_label.text = "Animação: " + ("Walk + Wave" if current_animation == WALK_WAVE_ANIMATION else current_animation) + " (locomoção)"
		animation_player.play(current_animation)
	else:
		._play_idle()
	_publish_status()

func _play_reaction(clip_name, event_text):
	if clip_name in WALK_COMBO_GESTURES and walking_active and automatic_movements_enabled and not manual_override and _walk_combo_is_enabled(clip_name):
		if _play_walk_combo(clip_name, "AUTOMÁTICO", false):
			return
	if animation_player != null and animation_player.has_animation(clip_name):
		animation_player.get_animation(clip_name).loop = false
	._play_reaction(clip_name, event_text)
	_publish_status()

func _walk_combo_is_enabled(gesture):
	return walk_combo_enabled.get(gesture, false) and walk_combo_available.get(gesture, false)

func _play_walk_combo(gesture, source, manual):
	var candidate_name = WALK_COMBO_NAMES.get(gesture, "")
	if not walking_active or manually_paused or animation_player == null or candidate_name.empty() or not animation_player.has_animation(candidate_name):
		walk_combo_errors[gesture] = "WALK_OR_CANDIDATE_UNAVAILABLE"
		walk_combo_available[gesture] = false
		if gesture == "Wave":
			walk_wave_available = false
			walk_wave_error = walk_combo_errors[gesture]
		push_error("WALK_COMBO_FALLBACK gesture=" + gesture + " reason=" + walk_combo_errors[gesture])
		_publish_status()
		return false
	var combo = animation_player.get_animation(candidate_name)
	combo.loop = false
	manual_override = manual
	is_reacting = true
	current_animation = candidate_name
	current_event = "Walk + " + gesture
	animation_source = source
	animation_label.text = "Animação: Walk + " + gesture
	event_label.text = "Último evento: " + current_event
	animation_player.play(candidate_name)
	print("WALK_COMBO_START gesture=" + gesture + " animation=" + candidate_name + " bones=" + ",".join(walk_combo_bones.get(gesture, [])) + " tracks=" + ",".join(walk_combo_tracks.get(gesture, [])))
	_publish_status()
	return true

func _on_animation_finished(clip_name):
	if speech_gesture_running and (clip_name == speech_animation or clip_name == WALK_COMBO_NAMES.get(speech_animation, "")):
		speech_gesture_running = false
	if clip_name in WALK_COMBO_NAMES.values():
		var gesture = ""
		for name in WALK_COMBO_NAMES:
			if WALK_COMBO_NAMES[name] == clip_name:
				gesture = name
				break
		print("WALK_COMBO_END gesture=" + gesture + " animation=" + clip_name + " resumed=" + str(walking_active and not manually_paused))
	if manual_override and not manually_paused and animation_player != null and animation_player.has_animation(clip_name):
		if not animation_player.get_animation(clip_name).loop:
			manual_override = false
			animation_source = "MANUAL" if walking_active else "GODOT"
	elif walking_active:
		manual_override = false
	._on_animation_finished(clip_name)
	_publish_status()

func _on_connection_changed(connected, detail):
	if not connected:
		walking_active = false
		automatic_walking = false
		manual_override = false
		manually_paused = false
		event_queue.clear()
		speech_active = false
		speech_gesture_pending = false
		speech_gesture_running = false
		if animation_player != null:
			_play_idle()
	._on_connection_changed(connected, detail)

func _publish_status():
	if status_enabled and tcp_server != null:
		var active_gesture = ""
		for gesture in WALK_COMBO_NAMES:
			if current_animation == WALK_COMBO_NAMES[gesture]:
				active_gesture = gesture
				break
		tcp_server.send_status({"audience_queue":audience_overlay.diagnostic_state(), "walking":walking_active, "live":live_mode, "speed":background_speed, "resolution":render_resolution, "animation":current_animation, "paused":manually_paused, "manual":manual_override, "automatic":automatic_movements_enabled, "source":animation_source, "reacting":is_reacting, "speaking":speech_active, "available":ANIMATION_NAMES, "scenery_moving":scenery_moving, "walk_wave_enabled":walk_wave_enabled, "walk_wave_available":walk_wave_available, "walk_wave_active":walking_active and current_animation == WALK_WAVE_ANIMATION, "walk_wave_error":walk_wave_error, "walk_combos":walk_combo_enabled, "walk_combo_available":walk_combo_available, "walk_combo_errors":walk_combo_errors, "walk_combo_active":active_gesture, "walk_combo_bones":walk_combo_bones.get(active_gesture, []), "walk_combo_tracks":walk_combo_tracks.get(active_gesture, [])})

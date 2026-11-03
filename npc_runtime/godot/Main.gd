extends Spatial

const CHARACTER_SCENE = "res://assets/character/Character.gltf"

var audience_overlay = null
var character = null
var animation_player = null
var current_animation = ""
var current_event = "Nenhum"
var event_queue = []
var is_reacting = false
var speech_active = false
var speech_gesture_pending = false
var speech_gesture_running = false
var speech_animation = "Wave"
var dropped_events = 0
var tcp_server = null
const MAX_QUEUE = 10
const EVENT_NAMES = ["idle", "talk", "dance", "gift", "comment", "follow"]
const ANIMATION_NAMES = ["Death", "Duck", "HitReact", "Idle", "Idle_Gun", "Idle_Shoot", "Jump", "Jump_Idle", "Jump_Land", "No", "Punch", "Run", "Run_Gun", "Run_Shoot", "Walk", "Walk_Gun", "Wave", "Yes"]
const SPEECH_ANIMATIONS = ["Idle", "Jump", "No", "Wave", "Yes"]
var manual_override = false
var manually_paused = false
var paused_position = 0.0

onready var animation_label = $HUD/Panel/AnimationLabel
onready var event_label = $HUD/Panel/EventLabel
onready var response_label = $HUD/Panel/ResponseLabel
onready var face_sync = $FaceSync

func _ready():
	audience_overlay = load("res://AudienceQueue.gd").new()
	add_child(audience_overlay)
	var packed = load(CHARACTER_SCENE)
	if packed == null:
		push_error("Não foi possível carregar Character.gltf")
		return
	character = packed.instance()
	character.name = "QuaterniusCharacter"
	$CharacterAnchor.add_child(character)

	face_sync.attach(character)

	animation_player = character.find_node("AnimationPlayer", true, false)
	if animation_player == null:
		push_error("AnimationPlayer não encontrado no Character.gltf")
		return
	if not animation_player.has_animation("Idle"):
		push_error("Animação Idle não encontrada")
		return

	var idle_clip = animation_player.get_animation("Idle")
	idle_clip.loop = true
	for clip_name in ["Wave", "Yes", "Jump", "Duck", "HitReact"]:
		if animation_player.has_animation(clip_name):
			animation_player.get_animation(clip_name).loop = false
	animation_player.connect("animation_finished", self, "_on_animation_finished")
	_play_idle()
	response_label.clip_text = true
	event_label.clip_text = true
	tcp_server = load("res://LocalTcpServer.gd").new()
	tcp_server.name = "LocalTcpServer"
	tcp_server.connect("event_received", self, "handle_event")
	tcp_server.connect("connection_changed", self, "_on_connection_changed")
	add_child(tcp_server)

func _unhandled_input(event):
	if event is InputEventKey and event.pressed and not event.echo:
		match event.scancode:
			KEY_1:
				handle_event("idle")
			KEY_2:
				handle_event("talk")
			KEY_3:
				handle_event("dance")
			KEY_4:
				handle_event("gift")
			KEY_5:
				handle_event("comment")
			KEY_6:
				handle_event("follow")

func handle_event(event_data):
	var payload = {}
	if typeof(event_data) == TYPE_STRING:
		payload = {"event": event_data}
	elif typeof(event_data) == TYPE_DICTIONARY:
		payload = event_data.duplicate(true)
	else:
		push_warning("NPC: evento deve ser texto ou objeto JSON")
		return false
	if payload.get("command", "") == "audience_queue":
		return audience_overlay.update_queue(payload)
	if payload.has("command"):
		return _handle_control(payload)
	if not payload.has("event") or typeof(payload["event"]) != TYPE_STRING:
		push_warning("NPC: campo event ausente ou inválido")
		return false
	var key = payload["event"].to_lower()
	if not key in EVENT_NAMES:
		push_warning("NPC: comando desconhecido")
		return false
	payload["event"] = key
	for field in ["user", "gift", "text"]:
		if payload.has(field):
			if typeof(payload[field]) != TYPE_STRING:
				push_warning("NPC: metadado inválido: " + field)
				return false
			var limit = 256 if field == "text" else 64
			payload[field] = payload[field].replace("\n", " ").replace("\r", " ").substr(0, limit)
	if payload.has("speaking") and (key != "talk" or typeof(payload["speaking"]) != TYPE_BOOL):
		push_warning("NPC: campo speaking inválido")
		return false
	if payload.has("gesture") and (key != "talk" or typeof(payload["gesture"]) != TYPE_STRING or not payload["gesture"] in SPEECH_ANIMATIONS):
		push_warning("NPC: gesto de fala inválido")
		return false
	if face_sync != null:
		if key == "talk" and payload.get("speaking", false) == true:
			face_sync.set_speaking(true)
		elif key == "idle" and payload.get("speech_end", false) == true:
			face_sync.set_speaking(false)
	if manual_override or manually_paused:
		return false
	if animation_player == null:
		return false
	if key == "idle" and payload.get("speech_end", false) == true:
		_set_speech_active(false)

		speech_gesture_pending = false
		if speech_gesture_running:
			animation_player.stop()
			speech_gesture_running = false
			is_reacting = false
			current_animation = ""
			if not event_queue.empty():
				_execute_event(event_queue.pop_front())
			else:
				_play_idle()
			return true
		if not is_reacting and event_queue.empty():
			_play_idle()
		return true
	if key == "talk" and payload.get("speaking", false) == true:
		_set_speech_active(true)

		speech_animation = payload.get("gesture", "Wave")
		speech_gesture_pending = true
		if is_reacting:
			return true
	if key == "idle":
		_set_speech_active(false)
		speech_gesture_pending = false
		speech_gesture_running = false
		event_queue.clear()
	elif is_reacting:
		if event_queue.size() >= MAX_QUEUE:
			dropped_events += 1
			if dropped_events == 1 or dropped_events % 10 == 0:
				push_warning("NPC: fila cheia; descartados=" + str(dropped_events))
			return false
		event_queue.append(payload)
		return true
	_execute_event(payload)
	return true

func _handle_control(payload):
	var command = payload.get("command", "")
	if typeof(command) != TYPE_STRING:
		return false
	if command == "animate":
		var clip_name = payload.get("animation", "")
		var repeat = payload.get("repeat", false)
		if typeof(clip_name) != TYPE_STRING or not clip_name in ANIMATION_NAMES:
			push_warning("NPC: animação desconhecida rejeitada")
			return false
		if typeof(repeat) != TYPE_BOOL or animation_player == null or not animation_player.has_animation(clip_name):
			push_warning("NPC: animação indisponível ou repetição inválida")
			return false
		manual_override = true
		manually_paused = false
		event_queue.clear()
		_set_speech_active(false)
		speech_gesture_pending = false
		speech_gesture_running = false
		is_reacting = true
		current_animation = clip_name
		current_event = "Simulação manual: " + clip_name
		animation_player.get_animation(clip_name).loop = repeat or clip_name == "Idle"
		animation_label.text = "Animação: " + clip_name + (" (repetindo)" if repeat else "")
		event_label.text = "Último evento: " + current_event
		animation_player.play(clip_name)
		return true
	if command == "pause":
		manually_paused = true
		manual_override = true
		event_queue.clear()
		_set_speech_active(false)
		speech_gesture_pending = false
		speech_gesture_running = false
		if animation_player != null:
			paused_position = animation_player.get_current_animation_position()
			animation_player.stop(false)
		animation_label.text = "Animação: Pausada"
		return true
	if command == "resume":
		manually_paused = false
		if animation_player != null and current_animation != "" and animation_player.has_animation(current_animation):
			animation_player.play(current_animation)
			animation_player.seek(paused_position, true)
			animation_label.text = "Animação: " + current_animation
		return true
	if command == "stop":
		manually_paused = false
		manual_override = true
		event_queue.clear()
		_set_speech_active(false)
		speech_gesture_pending = false
		speech_gesture_running = false
		if animation_player != null:
			animation_player.stop()
		current_animation = ""
		paused_position = 0.0
		is_reacting = false
		animation_label.text = "Animação: Parada"
		return true
	if command == "idle":
		manually_paused = false
		manual_override = false
		event_queue.clear()
		_set_speech_active(false)
		speech_gesture_pending = false
		speech_gesture_running = false
		_play_idle()
		return true
	push_warning("NPC: comando de controle desconhecido rejeitado")
	return false

func _execute_event(payload):
	var key = payload["event"]
	var user_name = payload.get("user", "")
	var user_suffix = " | " + user_name if not user_name.empty() else ""
	print("NPC evento: " + key)
	match key:
		"idle":
			current_event = "Comando manual: Idle"
			response_label.text = "Aguardando evento."
			event_label.text = "Último evento: " + current_event
			_play_idle()
		"talk":
			if payload.get("speaking", false) == true:
				_play_speech_gesture()
			else:
				current_event = "Gesto de fala (Wave)"
				response_label.text = "Olá! Estou aqui para conversar."
				_play_reaction("Wave", current_event)
		"dance":
			current_event = "Comemoração (Jump)"
			response_label.text = "Vamos comemorar!"
			_play_reaction("Jump", current_event)
		"gift":
			current_event = "Presente recebido" + user_suffix + (" | " + payload.get("gift", "") if payload.has("gift") else "")
			response_label.text = (user_name + ", " if not user_name.empty() else "") + "obrigado pelo presente!"
			_play_reaction("Jump", current_event)
		"comment":
			current_event = "Comentário recebido" + user_suffix
			response_label.text = (user_name + ": " if not user_name.empty() else "") + payload.get("text", "Comentário recebido!") + " | Obrigado por participar."
			_play_reaction("Wave", current_event)
		"follow":
			current_event = "Novo seguidor" + user_suffix
			response_label.text = "Bem-vindo" + (", " + user_name if not user_name.empty() else "") + "! Obrigado por seguir."
			_play_reaction("Yes", current_event)
		_:
			push_warning("Evento desconhecido: " + key)

func _set_speech_active(active):
	speech_active = active

func receive_event(event_name):
	handle_event(event_name)

func _play_reaction(clip_name, event_text):
	if animation_player == null or not animation_player.has_animation(clip_name):
		push_warning("Animação não disponível: " + clip_name)
		_play_idle()
		return
	is_reacting = true
	current_animation = clip_name
	event_label.text = "Último evento: " + event_text
	animation_label.text = "Animação: " + clip_name
	animation_player.play(clip_name)

func _play_idle():
	if animation_player == null:
		return
	is_reacting = false
	current_animation = "Idle"
	animation_label.text = "Animação: Idle"
	animation_player.play("Idle")

func _play_speech_gesture():
	if not speech_active or not speech_gesture_pending:
		return
	speech_gesture_pending = false
	if not speech_animation in SPEECH_ANIMATIONS or not animation_player.has_animation(speech_animation):
		speech_animation = "Idle"
	if speech_animation == "Idle":
		current_event = "Fala em andamento"
		_play_idle()
	else:
		speech_gesture_running = true
		current_event = "Gesto contextual de fala (" + speech_animation + ")"
		_play_reaction(speech_animation, current_event)

func _on_animation_finished(clip_name):
	if clip_name == current_animation and clip_name != "Idle":
		if speech_gesture_running and clip_name == speech_animation:
			speech_gesture_running = false
		if manual_override:
			if not animation_player.get_animation(clip_name).loop:
				current_animation = ""
				is_reacting = false
				animation_label.text = "Animação: concluída"
			return
		_play_idle()
		if not event_queue.empty():
			_execute_event(event_queue.pop_front())
		elif speech_active and speech_gesture_pending:
			_play_speech_gesture()

func _on_connection_changed(_connected, detail):
	if not _connected:
		_set_speech_active(false)

		speech_gesture_pending = false
		speech_gesture_running = false
	$HUD/Panel/TitleLabel.text = "ZUKO LIVE 3D | Quaternius | " + detail

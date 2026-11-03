extends Node

signal event_received(payload)
signal connection_changed(connected, detail)

const HOST = "127.0.0.1"
var PORT = 8765
const MAX_MESSAGE_BYTES = 4096
const MAX_READ_PER_FRAME = 4096
const MAX_LINES_PER_FRAME = 32

var server = TCP_Server.new()
var client = null
var line_buffer = PoolByteArray()
var pending = PoolByteArray()
var pending_index = 0
var rejected_messages = 0

func _ready():
	if OS.has_environment("NPC_SHOW_PORT"):
		var override_port = int(OS.get_environment("NPC_SHOW_PORT"))
		if override_port < 1024 or override_port > 65535:
			push_error("NPC SHOW: porta inválida")
			return
		PORT = override_port
	var error = server.listen(PORT, HOST)
	if error != OK:
		print("NPC TCP: porta local indisponível: " + str(error))
		emit_signal("connection_changed", false, "TCP indisponível (8765; erro " + str(error) + ")")
		return
	print("NPC TCP: escutando somente em " + HOST + ":" + str(PORT))
	emit_signal("connection_changed", false, "Python: desconectado")

func _process(_delta):
	if not server.is_listening():
		return
	if client != null and client.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		_disconnect_client()
	# Um cliente por vez; conexões extras não interrompem a sessão atual.
	if server.is_connection_available():
		var incoming = server.take_connection()
		if client != null:
			incoming.disconnect_from_host()
		else:
			client = incoming
			client.set_no_delay(true)
			var hello = "{\"app\":\"NPC_LIVE_SHOW\",\"protocol\":1}\n".to_utf8()
			var sent = client.put_partial_data(hello)
			if sent[0] != OK or sent[1] != hello.size():
				_disconnect_client()
				return
			print("NPC TCP: Python conectado")
			emit_signal("connection_changed", true, "Python: conectado")
	if client == null:
		return
	if pending_index >= pending.size():
		var available = client.get_available_bytes()
		if available <= 0:
			return
		var received = client.get_partial_data(min(available, MAX_READ_PER_FRAME))
		if received[0] != OK:
			_disconnect_client()
			return
		pending = received[1]
		pending_index = 0
	var lines = 0
	while pending_index < pending.size() and lines < MAX_LINES_PER_FRAME:
		var byte = pending[pending_index]
		pending_index += 1
		if byte == 10:
			_process_line(line_buffer)
			line_buffer = PoolByteArray()
			lines += 1
		else:
			line_buffer.append(byte)
			if line_buffer.size() > MAX_MESSAGE_BYTES:
				_reject("mensagem excede 4096 bytes; conexão encerrada")
				_disconnect_client()
				return

func _process_line(bytes):
	var text = bytes.get_string_from_utf8().strip_edges()
	if text.empty():
		return
	var parsed = JSON.parse(text)
	if parsed.error != OK or typeof(parsed.result) != TYPE_DICTIONARY:
		_reject("JSON inválido ou objeto ausente")
		return
	emit_signal("event_received", parsed.result)

func _reject(reason):
	rejected_messages += 1
	if rejected_messages == 1 or rejected_messages % 10 == 0:
		push_warning("NPC TCP: " + reason + " (rejeitados=" + str(rejected_messages) + ")")

func send_status(payload):
	if client == null or client.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		return
	var data = (JSON.print({"type":"presentation_status", "state":payload}) + "\n").to_utf8()
	var sent = client.put_partial_data(data)
	if sent[0] != OK or sent[1] != data.size():
		_disconnect_client()

func _disconnect_client():
	if client != null:
		client.disconnect_from_host()
		client = null
		print("NPC TCP: Python desconectado")
		emit_signal("connection_changed", false, "Python: desconectado")
	line_buffer = PoolByteArray()
	pending = PoolByteArray()
	pending_index = 0

func _exit_tree():
	_disconnect_client()
	server.stop()


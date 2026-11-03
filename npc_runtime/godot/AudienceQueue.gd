extends CanvasLayer

var session = ""
var version = -1
var retired_sessions = []
var last_update = 0
var confirmed_text = ""
var panel = null
var label = null

func _ready():
	name = "AudienceQueue"
	layer = 20
	panel = PanelContainer.new()
	panel.anchor_left = 1.0
	panel.anchor_right = 1.0
	panel.margin_left = -280
	panel.margin_right = -12
	panel.margin_top = 18
	panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var style = StyleBoxFlat.new()
	style.bg_color = Color(0.03, 0.05, 0.09, 0.87)
	style.content_margin_left = 12
	style.content_margin_right = 12
	style.content_margin_top = 10
	style.content_margin_bottom = 10
	panel.add_stylebox_override("panel", style)
	label = Label.new()
	label.autowrap = true
	label.rect_min_size = Vector2(244, 0)
	panel.add_child(label)
	add_child(panel)
	label.text = "FILA · AGUARDANDO CONEXÃO"
	panel.show()

func _process(_delta):
	if OS.get_ticks_msec() - last_update > 2500 and panel != null:
		label.text = "FILA · SEM CONEXÃO"
		panel.show()

func update_queue(payload):
	if typeof(payload.get("session")) != TYPE_STRING or typeof(payload.get("rows")) != TYPE_ARRAY:
		return false
	var incoming = int(payload.get("version", -1))
	if payload.session == session and incoming < version:
		return false
	if payload.session == session and incoming == version:
		last_update = OS.get_ticks_msec()
		label.text = confirmed_text
		panel.show()
		return true
	if payload.session != session:
		if payload.session in retired_sessions:
			return false
		if not session.empty():
			retired_sessions.append(session)
			if retired_sessions.size() > 32:
				retired_sessions.pop_front()
	session = payload.session
	version = incoming
	last_update = OS.get_ticks_msec()
	var lines = PoolStringArray()
	var current = payload.get("current", {})
	if typeof(current) == TYPE_DICTIONARY and not current.empty():
		lines.append("RESPONDENDO AGORA: " + display_name(current))
	if not payload.rows.empty():
		lines.append("PRÓXIMAS RESPOSTAS")
	for i in range(min(4, payload.rows.size())):
		var row = payload.rows[i]
		if typeof(row) != TYPE_DICTIONARY:
			return false
		var state = str(row.get("state", "aguardando")).to_upper()
		if i == 0 and state == "AGUARDANDO":
			state = "PRÓXIMO"
		lines.append(str(i + 1) + ". " + display_name(row) + " — " + state)
	var extra = max(0, int(payload.get("extra", 0)))
	if extra > 0:
		lines.append("+" + str(extra) + " aguardando")
	if lines.empty():
		lines.append("FILA VAZIA")
	confirmed_text = lines.join("\n")
	label.text = confirmed_text
	panel.show()
	return true

func display_name(row):
	var value = str(row.get("name", "")).replace("\n", " ").replace("\r", " ").substr(0, 48)
	return "@" + value if not value.empty() else "Espectador"

# Content-free readback lets Python verify application, not merely socket writes.
func diagnostic_state():
	return {"session":session, "version":version, "visible":panel.visible, "text_sha256":label.text.sha256_text(), "node_path":str(get_path()), "canvas_layer":layer, "panel_position":[panel.rect_global_position.x,panel.rect_global_position.y], "panel_size":[panel.rect_size.x,panel.rect_size.y], "viewport_size":[get_viewport().get_visible_rect().size.x,get_viewport().get_visible_rect().size.y]}

extends SceneTree
func _init():
	call_deferred("check")
func check():
	var overlay = load("res://AudienceQueue.gd").new()
	get_root().add_child(overlay)
	var data = {"session":"offline","version":2,"rows":[{"id":"1","name":"João","state":"aguardando"},{"id":"2","name":"Ana","state":"aguardando"},{"id":"3","name":"Carlos","state":"aguardando"},{"id":"4","name":"Bia","state":"aguardando"}],"extra":2,"current":{}}
	assert(overlay.update_queue(data))
	assert(overlay.panel.visible)
	assert(overlay.label.text.find("+2 aguardando") >= 0)
	data.version = 1
	assert(not overlay.update_queue(data))
	data.version = 3
	data.current = {"id":"0","name":"José"}
	assert(overlay.update_queue(data))
	assert(overlay.label.text.find("RESPONDENDO AGORA") >= 0)
	data.rows = []
	data.current = {}
	data.extra = 0
	data.version = 4
	assert(overlay.update_queue(data))
	assert(overlay.panel.visible)
	assert(overlay.label.text == "FILA VAZIA")
	assert(load("res://Main.gd") != null)
	data.session = "restart"
	data.version = 1
	assert(overlay.update_queue(data))
	data.session = "offline"
	data.version = 100
	assert(not overlay.update_queue(data))
	overlay.last_update = -3000
	overlay._process(0)
	assert(overlay.panel.visible)
	assert(overlay.label.text == "FILA · SEM CONEXÃO")
	data.session = "restart"
	data.version = 1
	assert(overlay.update_queue(data))
	assert(overlay.label.text == "FILA VAZIA")
	print("AUDIENCE_OVERLAY_NATIVE_OK")
	quit()

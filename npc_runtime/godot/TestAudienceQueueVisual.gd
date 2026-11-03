extends SceneTree
var main = null
func _init():
	call_deferred("show_test")
func show_test():
	main = load("res://Main.tscn").instance()
	get_root().add_child(main)
	var timer = Timer.new()
	timer.wait_time = 0.5
	timer.connect("timeout", self, "refresh")
	get_root().add_child(timer)
	timer.start()
	refresh()
	print("OFFLINE_VISUAL_INJECTED")
	yield(create_timer(35), "timeout")
	quit()
func refresh():
	main.audience_overlay.update_queue({"session":"offline-visual","version":1,"rows":[{"id":"1","name":"Teste João","state":"aguardando"},{"id":"2","name":"Teste Ana","state":"aguardando"},{"id":"3","name":"Teste Carlos","state":"aguardando"},{"id":"4","name":"Teste Bia","state":"aguardando"}],"extra":2,"current":{}})

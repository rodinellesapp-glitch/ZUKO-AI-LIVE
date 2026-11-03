extends SceneTree
func _init():
	var scene = load("res://assets/character/Character.gltf").instance()
	get_root().add_child(scene)
	var player = scene.find_node("AnimationPlayer", true, false)
	var result = load("res://WalkWaveCandidate.gd").build(player)
	if result == null:
		printerr("WALK_WAVE_FAILED")
		quit(1)
	else:
		print("WALK_WAVE_BUILT tracks=", result.get_track_count())
		quit(0)

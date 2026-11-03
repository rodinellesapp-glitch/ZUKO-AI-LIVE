extends Reference

const WAVE_BONES = ["Shoulder.L", "UpperArm.L", "LowerArm.L", "Fist.L", "Shoulder.R", "UpperArm.R", "LowerArm.R", "Fist.R"]
const YES_BONES = ["Head", "Ear2.L", "Ear2.R", "Ear3.L", "Ear3.R"]
const NO_BONES = ["Head"]

static func bones_for(gesture):
	match gesture:
		"Wave": return WAVE_BONES.duplicate()
		"Yes": return YES_BONES.duplicate()
		"No": return NO_BONES.duplicate()
	return []

static func build(player, gesture):
	if player == null or not player.has_animation("Walk") or not player.has_animation(gesture):
		return null
	if gesture == "Wave":
		var wave = load("res://WalkWaveCandidate.gd").build(player)
		if wave == null:
			return null
		var wave_tracks = []
		for track in range(wave.get_track_count()):
			var wave_path = wave.track_get_path(track)
			if wave_path.get_subname_count() > 0 and str(wave_path.get_subname(0)) in WAVE_BONES:
				wave_tracks.append(str(wave_path))
		return {"animation": wave, "bones": WAVE_BONES.duplicate(), "tracks": wave_tracks, "count": wave_tracks.size()}
	var mask = bones_for(gesture)
	if mask.empty():
		return null
	var base = player.get_animation("Walk").duplicate(true)
	var overlay = player.get_animation(gesture)
	var replaced = []
	var track_paths = []
	for track in range(base.get_track_count() - 1, -1, -1):
		var path = base.track_get_path(track)
		if path.get_subname_count() == 0 or not str(path.get_subname(0)) in mask:
			continue
		var source = overlay.find_track(path)
		if source < 0 or base.track_get_type(track) != Animation.TYPE_TRANSFORM or overlay.track_get_type(source) != Animation.TYPE_TRANSFORM:
			return null
		base.remove_track(track)
		var added = base.add_track(Animation.TYPE_TRANSFORM)
		base.track_set_path(added, path)
		base.track_set_interpolation_type(added, overlay.track_get_interpolation_type(source))
		for key in range(overlay.track_get_key_count(source)):
			var value = overlay.track_get_key_value(source, key)
			var at = overlay.track_get_key_time(source, key) * base.length / overlay.length
			base.transform_track_insert_key(added, at, value.location, value.rotation, value.scale)
		replaced.append(str(path.get_subname(0)))
		track_paths.append(str(path))
	if replaced.size() != mask.size():
		return null
	base.loop = false
	return {"animation": base, "bones": mask, "tracks": track_paths, "count": replaced.size()}

extends Reference

# Builds a separate local Walk + Wave animation; original imported clips stay unchanged.
const ARM_BONES = ["Shoulder.L", "UpperArm.L", "LowerArm.L", "Fist.L", "Shoulder.R", "UpperArm.R", "LowerArm.R", "Fist.R"]

static func build(player):
	if player == null or not player.has_animation("Walk") or not player.has_animation("Wave"):
		return null
	var base = player.get_animation("Walk").duplicate(true)
	var wave = player.get_animation("Wave")
	var count = 0
	for track in range(base.get_track_count() - 1, -1, -1):
		var path = base.track_get_path(track)
		if path.get_subname_count() == 0 or not str(path.get_subname(0)) in ARM_BONES:
			continue
		var other = wave.find_track(path)
		if other < 0 or wave.track_get_type(other) != Animation.TYPE_TRANSFORM:
			return null
		base.remove_track(track)
		var added = base.add_track(Animation.TYPE_TRANSFORM)
		base.track_set_path(added, path)
		base.track_set_interpolation_type(added, wave.track_get_interpolation_type(other))
		for key in range(wave.track_get_key_count(other)):
			var value = wave.track_get_key_value(other, key)
			var at = wave.track_get_key_time(other, key) * base.length / wave.length
			base.transform_track_insert_key(added, at, value.location, value.rotation, value.scale)
		count += 1
	if count != ARM_BONES.size():
		return null
	base.loop = true
	return base

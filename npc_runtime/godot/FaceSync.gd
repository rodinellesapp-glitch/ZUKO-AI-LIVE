extends Node

# Reversible facial overlay. It attaches to the existing Head bone and never edits the GLTF mesh.
export(bool) var enabled = true

const OPEN_SPEED_HZ = 4.6
const FACE_NOSE_POSITION = Vector3(0.0, 0.54, 0.87)
const FACE_MOUTH_POSITION = Vector3(0.0, 0.29, 0.88)

var speaking = false
var elapsed = 0.0
var mouth_value = 0.0
var mouth = null
var smile = null
var attached = false

func attach(character):
	if not enabled:
		print("FACE_SYNC_DISABLED")
		return false
	var skeleton = _find_head_skeleton(character)
	if skeleton == null:
		push_error("FACE_SYNC_HEAD_BONE_NOT_FOUND")
		return false
	var attachment = BoneAttachment.new()
	attachment.name = "FaceSyncOnHead"
	attachment.bone_name = "Head"
	skeleton.add_child(attachment)
	var face = Spatial.new()
	face.name = "FaceSyncOverlay"
	attachment.add_child(face)

	var dark = SpatialMaterial.new()
	dark.albedo_color = Color(0.012, 0.025, 0.045, 1.0)
	dark.roughness = 0.92
	var nose_material = SpatialMaterial.new()
	nose_material.albedo_color = Color(0.90, 0.43, 0.20, 1.0)
	nose_material.roughness = 0.82
	var nose = MeshInstance.new()
	nose.name = "FaceSyncNose"
	var nose_mesh = SphereMesh.new()
	nose_mesh.radius = 0.066
	nose_mesh.height = 0.13
	nose.mesh = nose_mesh
	nose.material_override = nose_material
	nose.translation = FACE_NOSE_POSITION
	nose.scale = Vector3(0.88, 0.90, 0.70)
	face.add_child(nose)

	mouth = MeshInstance.new()
	mouth.name = "FaceSyncMouth"
	var mouth_mesh = SphereMesh.new()
	mouth_mesh.radius = 0.145
	mouth_mesh.height = 0.30
	mouth.mesh = mouth_mesh
	mouth.material_override = dark
	mouth.translation = FACE_MOUTH_POSITION
	mouth.scale = Vector3(0.92, 0.06, 0.24)
	mouth.visible = false
	face.add_child(mouth)

	smile = Spatial.new()
	smile.name = "FaceSyncRestingSmile"
	smile.translation = FACE_MOUTH_POSITION + Vector3(0.0, -0.007, 0.008)
	face.add_child(smile)
	var smile_x = [-0.120, -0.090, -0.060, -0.030, 0.0, 0.030, 0.060, 0.090, 0.120]
	for i in range(smile_x.size()):
		var point = MeshInstance.new()
		var point_mesh = SphereMesh.new()
		point_mesh.radius = 0.017
		point_mesh.height = 0.023
		point.mesh = point_mesh
		point.material_override = dark
		var smile_curve = -0.022 * (1.0 - abs(smile_x[i]) / 0.120)
		point.translation = Vector3(smile_x[i], smile_curve, 0.0)
		smile.add_child(point)
	attached = true
	print("FACE_SYNC_READY bone=Head mode=confirmed_playback_pulse rms=unavailable")
	return true

func _find_head_skeleton(node):
	if node is Skeleton and node.find_bone("Head") >= 0:
		return node
	for child in node.get_children():
		var found = _find_head_skeleton(child)
		if found != null:
			return found
	return null

func set_speaking(active):
	speaking = bool(active) and enabled and attached
	if not speaking:
		elapsed = 0.0
	print("FACE_SYNC_PLAYBACK active=" + str(speaking))

func _process(delta):
	if not attached or mouth == null:
		return
	var target = 0.0
	if speaking:
		elapsed += delta
		# Clearly marked fallback: a soft speech-rate pulse because the TTS callbacks expose
		# playback state but not PCM/RMS amplitude. Smooth fades avoid hard snapping.
		target = 0.12 + 0.72 * max(0.0, sin(elapsed * PI * 2.0 * OPEN_SPEED_HZ))
	mouth_value = lerp(mouth_value, target, 1.0 - exp(-delta * 15.0))
	mouth.visible = mouth_value > 0.025
	mouth.scale.x = lerp(0.92, 1.08, mouth_value)
	mouth.scale.y = lerp(0.06, 0.88, mouth_value)
	smile.visible = mouth_value < 0.06
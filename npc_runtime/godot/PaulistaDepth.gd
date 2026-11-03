extends Spatial
# Lightweight 2.5D stage: actual ground/road depth, repeated street furniture,
# an artistic distant plate. No camera zoom, image deformation or lateral pan.
const PERIOD = 120.0
const FAR_Z = -100.0
const END_Z = 20.0
var travel = 0.0
var movers = []
var material_cache = {}
var ground_y = 0.0

func texture_file(path, repeat_texture=false):
	var image = Image.new()
	if image.load(path) != OK:
		push_error("Paulista: missing local asset " + path)
		return null
	image.generate_mipmaps()
	var texture = ImageTexture.new()
	var flags = Texture.FLAG_MIPMAPS | Texture.FLAG_FILTER
	if repeat_texture:
		flags |= Texture.FLAG_REPEAT | Texture.FLAG_ANISOTROPIC_FILTER
	texture.create_from_image(image, flags)
	return texture

func solid(color):
	var key = str(color)
	if material_cache.has(key):
		return material_cache[key]
	var material = SpatialMaterial.new()
	material.albedo_color = color
	material.roughness = 0.85
	material_cache[key] = material
	return material

func box(parent, position, size, material):
	var node = MeshInstance.new()
	var mesh = CubeMesh.new()
	mesh.size = size
	node.mesh = mesh
	node.material_override = material
	node.translation = position
	node.cast_shadow = GeometryInstance.SHADOW_CASTING_SETTING_OFF
	parent.add_child(node)
	return node

func rounded_shape(parent, position, size, material, segments=12):
	var node = MeshInstance.new()
	var mesh = SphereMesh.new()
	mesh.radial_segments = segments
	mesh.rings = 6
	node.mesh = mesh
	node.scale = size
	node.translation = position
	node.material_override = material
	node.cast_shadow = GeometryInstance.SHADOW_CASTING_SETTING_OFF
	parent.add_child(node)
	return node

func moving(node, z):
	node.translation.z = z
	movers.append({"node":node,"z":z})

func _ready():
	var parent = get_parent()
	# Keep the old scene node and old asset intact for rollback.
	parent.get_node("CityBackground").visible = false
	var camera = parent.get_node("Camera")
	camera.translation = Vector3(0, 1.8, 9.5)
	camera.look_at(Vector3(0, 2.0, 0), Vector3.UP)
	# Same character scale/anchor/rig. A wider margin protects head/arms in 9:16.
	camera.fov = 40.0
	parent.get_node("KeyLight").light_color = Color(1.0, 0.85, 0.66)
	parent.get_node("KeyLight").light_energy = 0.65
	parent.get_node("FillLight").light_energy = 0.20
	var environment = parent.get_node("WorldEnvironment").environment.duplicate()
	environment.ambient_light_color = Color(0.82,0.84,0.88)
	environment.ambient_light_energy = 0.68
	environment.fog_enabled = true
	environment.fog_color = Color(0.64,0.52,0.38)
	environment.fog_sun_color = Color(1.0,0.75,0.40)
	environment.fog_depth_begin = 38.0
	environment.fog_depth_end = 88.0
	parent.get_node("WorldEnvironment").environment = environment

	var plate = MeshInstance.new()
	plate.name = "DistantPaulista"
	var quad = QuadMesh.new()
	quad.size = Vector2(125.0,70.3125)
	plate.mesh = quad
	plate.translation = Vector3(0,13.0,-80.0)
	var plate_material = SpatialMaterial.new()
	plate_material.flags_unshaded = true
	plate_material.flags_disable_ambient_light = true
	plate_material.params_cull_mode = SpatialMaterial.CULL_DISABLED
	plate_material.albedo_texture = texture_file("res://assets/paulista-depth/paulista-clean-sunset.png")
	plate.material_override = plate_material
	plate.cast_shadow = GeometryInstance.SHADOW_CASTING_SETTING_OFF
	add_child(plate)

	var pavement = SpatialMaterial.new()
	pavement.albedo_texture = texture_file("res://assets/paulista-depth/sidewalk-stone.png", true)
	pavement.albedo_color = Color(0.72,0.66,0.58)
	pavement.uv1_scale = Vector3(2,2,1)
	pavement.roughness = 0.9
	var road = solid(Color(0.16,0.16,0.17))
	var curb = solid(Color(0.64,0.58,0.47))
	var tactile = solid(Color(0.66,0.46,0.17))
	var stripe = solid(Color(0.76,0.72,0.61))
	# Every segment has an integer texture period; joins stay aligned at recycling.
	for i in range(30):
		var segment = Spatial.new()
		add_child(segment)
		moving(segment, FAR_Z + i * 4.0)
		box(segment,Vector3(0,-0.09,0),Vector3(5.4,0.18,4),pavement)
		box(segment,Vector3(2.77,-0.13,0),Vector3(0.14,0.26,4),curb)
		box(segment,Vector3(9,-0.20,0),Vector3(12.3,0.1,4),road)
		box(segment,Vector3(-1.65,0.006,0),Vector3(0.21,0.008,4),tactile)
		for j in range(3):
			box(segment,Vector3(-1.73+j*0.08,0.014,0),Vector3(0.015,0.012,4),curb)
		box(segment,Vector3(6,-0.14,0),Vector3(0.08,0.01,1.8),stripe)

	var tree_material = SpatialMaterial.new()
	tree_material.albedo_texture = texture_file("res://assets/paulista-depth/paulista-tree.png")
	tree_material.flags_unshaded = true
	tree_material.params_use_alpha_scissor = true
	tree_material.params_alpha_scissor_threshold = 0.45
	tree_material.params_cull_mode = SpatialMaterial.CULL_DISABLED
	var tree_mesh = QuadMesh.new()
	tree_mesh.size = Vector2(5.4,5.4)
	var metal = solid(Color(0.11,0.10,0.08))
	var planter_material = solid(Color(0.43,0.39,0.31))
	var planter_mesh = CylinderMesh.new()
	planter_mesh.top_radius = 0.64
	planter_mesh.bottom_radius = 0.50
	planter_mesh.height = 0.48
	planter_mesh.radial_segments = 10
	var tree_offsets = [0.0,-0.8,0.6,-0.4,0.9,-0.5,0.3,-0.7,0.5,-0.2,0.8,-0.4]
	for i in range(12):
		var furniture = Spatial.new()
		add_child(furniture)
		moving(furniture,FAR_Z+i*10.0+tree_offsets[i])
		var planter = MeshInstance.new()
		planter.mesh = planter_mesh
		planter.material_override = planter_material
		planter.translation = Vector3(-3.2,0.24,0)
		planter.cast_shadow = GeometryInstance.SHADOW_CASTING_SETTING_OFF
		furniture.add_child(planter)
		var tree = MeshInstance.new()
		tree.mesh = tree_mesh
		tree.material_override = tree_material
		var tree_x = -3.2 + float(i%3-1)*0.12
		var tree_scale = 0.92 + float(i%3)*0.08
		tree.translation = Vector3(tree_x,2.95*tree_scale,0)
		tree.scale = Vector3(tree_scale,tree_scale,1.0)
		tree.cast_shadow = GeometryInstance.SHADOW_CASTING_SETTING_OFF
		furniture.add_child(tree)
		box(furniture,Vector3(2.55,0.42,0),Vector3(0.065,0.84,0.065),metal)
		box(furniture,Vector3(2.55,0.42,4),Vector3(0.065,0.84,0.065),metal)
		box(furniture,Vector3(2.55,0.68,2),Vector3(0.025,0.025,4),metal)

	var facade = SpatialMaterial.new()
	facade.albedo_texture = texture_file("res://assets/paulista-depth/paulista-facade.png",true)
	facade.flags_unshaded = true
	facade.params_cull_mode = SpatialMaterial.CULL_DISABLED
	var facade_mesh = QuadMesh.new()
	facade_mesh.size = Vector2(12,4)
	for i in range(10):
		var building = Spatial.new()
		add_child(building)
		moving(building,FAR_Z+i*12.0)
		var wall = MeshInstance.new()
		wall.mesh = facade_mesh
		wall.material_override = facade
		wall.rotation_degrees.y = 90
		wall.translation = Vector3(-4.1,2,0)
		wall.cast_shadow = GeometryInstance.SHADOW_CASTING_SETTING_OFF
		building.add_child(wall)
	# Small low-poly traffic silhouettes are actual depth objects, not video.
	var glass = solid(Color(0.13,0.19,0.20))
	var tire = solid(Color(0.06,0.055,0.05))
	var lamp = solid(Color(1.0,0.72,0.36))
	var taillamp = solid(Color(0.62,0.12,0.07))
	var vehicle_offsets = [0.0,1.1,-0.5,0.8,-0.9,0.3,-0.2,1.0,-0.7,0.4]
	var wheel_mesh = CylinderMesh.new()
	wheel_mesh.top_radius = 0.21
	wheel_mesh.bottom_radius = 0.21
	wheel_mesh.height = 0.14
	wheel_mesh.radial_segments = 10
	for i in range(10):
		var car = Spatial.new()
		add_child(car)
		moving(car,FAR_Z+i*12.0+3.0+vehicle_offsets[i])
		var x = 4.4 if i%2==0 else 8.1
		var paints = [Color(0.72,0.70,0.64),Color(0.27,0.29,0.29),Color(0.36,0.18,0.13)]
		var paint = solid(paints[i%paints.size()])
		var vehicle_scale = 0.94 + float(i%3)*0.06
		car.scale = Vector3(vehicle_scale,vehicle_scale,vehicle_scale)
		rounded_shape(car,Vector3(x,0.39,0),Vector3(0.82,0.34,1.65),paint,12)
		rounded_shape(car,Vector3(x,0.71,-0.10),Vector3(0.57,0.30,0.80),glass,12)
		rounded_shape(car,Vector3(x,0.96,-0.12),Vector3(0.51,0.10,0.64),paint,10)
		for side in [-1,1]:
			for axle in [-1,1]:
				var wheel = MeshInstance.new()
				wheel.mesh = wheel_mesh
				wheel.rotation_degrees.z = 90
				wheel.translation = Vector3(x+side*0.70,0.22,axle*0.98)
				wheel.material_override = tire
				wheel.cast_shadow = GeometryInstance.SHADOW_CASTING_SETTING_OFF
				car.add_child(wheel)
		for side in [-1,1]:
			rounded_shape(car,Vector3(x+side*0.50,0.42,1.54),Vector3(0.12,0.07,0.05),lamp,8)
			rounded_shape(car,Vector3(x+side*0.50,0.42,-1.54),Vector3(0.10,0.07,0.05),taillamp,8)
	# Soft procedural contact shadow. No light shadow maps on the GT 730.
	var shadow = MeshInstance.new()
	var shadow_mesh = QuadMesh.new()
	shadow_mesh.size = Vector2(2.4,1.6)
	shadow.mesh = shadow_mesh
	shadow.rotation_degrees.x = -90
	shadow.translation = Vector3(0,0.025,0.3)
	var shadow_shader = Shader.new()
	shadow_shader.code = "shader_type spatial; render_mode unshaded,blend_mix,depth_draw_never,cull_disabled; void fragment(){float r=length((UV-vec2(.5))*2.); ALBEDO=vec3(.13,.09,.055); ALPHA=(1.-smoothstep(.05,1.,r))*.65;}"
	var shadow_material = ShaderMaterial.new()
	shadow_material.shader = shadow_shader
	shadow.material_override = shadow_material
	shadow.cast_shadow = GeometryInstance.SHADOW_CASTING_SETTING_OFF
	add_child(shadow)

func advance(delta, active, speed):
	if not active:
		return
	# Character stays near the tracking camera; world travels toward camera (+Z).
	travel = fmod(travel + min(delta,0.1) * 1.8 * speed, PERIOD)
	for mover in movers:
		mover.node.translation.z = FAR_Z + fposmod(mover.z - FAR_Z + travel, PERIOD)

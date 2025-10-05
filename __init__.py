import bpy
import bmesh
from bpy.props import StringProperty, EnumProperty, IntProperty, FloatProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper
from bpy_extras.io_utils import ExportHelper
import os
import struct
import math
import mathutils
from bpy.types import ShaderNodeCustomGroup
from bpy.app.handlers import persistent

bl_info = {
    "name": "Blender B3D",
    "description": "Exporter for Blitz3D B3D Models",
    "author": "Yacker",
    "version": (0, 2, 0),
    "blender": (4, 5, 2),
    "location": "File > Import-Export > B3D Model (.b3d) ",
    "warning": "",
    "category": "Import-Export",
}

def WriteFloat(f, v):
    f.write(struct.pack('<f', v))

def WriteInt32(f, v):
    f.write(struct.pack('<i', v))

def WriteUInt32(f, v):
    f.write(struct.pack('<I', v))

def WriteInt16(f, v):
    f.write(struct.pack('<h', v))

def WriteUInt16(f, v):
    f.write(struct.pack('<H', v))

def WriteInt8(f, v):
    f.write(struct.pack('b', v))

def WriteUInt8(f, v):
    f.write(struct.pack('B', v))

def WriteString(f, v):
    for c in v:
        WriteUInt8(f,ord(c))
    WriteUInt8(f,0)
    
class ExportB3D(bpy.types.Operator, ExportHelper):
    """Export a B3D Model"""
    bl_idname = "export.b3d_model"
    bl_label = "Export B3D"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".b3d"
    filter_glob: StringProperty(
        default="*.b3d",
        options={'HIDDEN'})
    
    convert_coords: BoolProperty(
        name="Convert blender coords to Blitz3D coords",
        description="Blender uses Z up, and Blitz3D uses Y up. Tick this to automatically convert between these coordinate systems.",
        default=True,
    )
    export_as_one: BoolProperty(
        name="Export all selected as one file",
        description="Turning this on will disable exporting object transform info",
        default=True,
    )
    def execute(self, context):
        return b3d_export(self.filepath,self.convert_coords,self.export_as_one)

class TEXSBlock():
    def __init__(self):
        self.flags = 0 # 0x10000 for UV2
        self.blend = 2
        self.x_offs = 0
        self.y_offs = 0
        self.x_scale = 1.0
        self.y_scale = 1.0
        self.rotation = 0
        self.path = ""

class BRUSBlock():
    def __init__(self):
        self.mat_name = ""
        self.r = 1
        self.g = 1
        self.b = 1
        self.a = 1
        self.shiny = 0
        self.blend = 1
        self.fx = 0 # 0x1 - fullbright, 0x2 - vert color, 0x4 - flat shading, 0x8 - no fog, 0x10 - double sided, 0x20 - vert alpha, 0x2000 - alpha test(mask), 0x4000 - conditional lights, 0x8000 - emissive?
        self.textures = []

class NODEBlock():
    def __init__(self):
        self.mesh = None
        self.bone = None
        self.name = ""
        self.posX = 0
        self.posY = 0
        self.posZ = 0
        self.scaleX = 1.0
        self.scaleY = 1.0
        self.scaleZ = 1.0
        self.rotW = 1.0
        self.rotX = 0
        self.rotY = 0
        self.rotZ = 0
        self.subNodes = []
        self.keyNodes = []
        self.animNodes = []
        
        # here to keep things easy for me
        self.boneInd = -1

class BONEBlock():
    def __init__(self):
        self.vert = 0
        self.weight = 0

class VERTBlock():
    def __init__(self):
        self.flags = 0x1
        self.tex_coord_count = 0
        self.tex_coord_components = 2
        self.verts = []

class B3DVert():
    def __init__(self):
        self.x = 0
        self.y = 0
        self.z = 0
        self.nx = 0
        self.ny = 0
        self.nz = 0
        self.r = 1
        self.g = 1
        self.b = 1
        self.a = 1
        self.u = []
        self.v = []
        # NOT included in this block, but there's not really a practical other place to put items
        self.weightInds = []
        self.weights = []

class TRISBlock():
    def __init__(self):
        self.brushId = 0
        self.tris = []

class MESHBlock():
    def __init__(self):
        self.brushId = -1
        self.vertBlock = VERTBlock()
        self.triBlocks = []

def CreateTexs(obj):
    TexsBlock = []#TEXSBlock()
    for mat in obj.data.materials:
        from_socket_to_socket = dict([[link.from_socket, link.to_socket] for link in mat.node_tree.links])
        to_socket_from_socket = dict([[link.to_socket, link.from_socket] for link in mat.node_tree.links])
        
        simple_mats = True
        for node in mat.node_tree.nodes:
            if node.bl_idname == "B3DShader":
                simple_mats = False
        
        if simple_mats == False:
            for node in mat.node_tree.nodes:
                if node.bl_idname != "B3DTextureInput":
                    continue
                
                blenderImage = to_socket_from_socket.get(node.inputs[0], None)
                if blenderImage == None:
                    continue
                blenderImage = blenderImage.node
                if (blenderImage.image == None):
                    continue
                if blenderImage.image.filepath == "":
                    continue
                
                B3DTex = TEXSBlock()
                B3DTex.blenderTex = blenderImage
                B3DTex.path = os.path.basename(blenderImage.image.filepath)
                B3DTex.blend = int(node.blend_type)
                
                if node.inputs[1].default_value == True:
                    B3DTex.flags |= 1
                if node.inputs[2].default_value == True:
                    B3DTex.flags |= 2
                if node.inputs[3].default_value == True:
                    B3DTex.flags |= 4
                if node.inputs[4].default_value == True:
                    B3DTex.flags |= 8
                if node.inputs[5].default_value == True:
                    B3DTex.flags |= 0x10000
                if node.inputs[6].default_value == True:
                    B3DTex.flags |= 0x400
                    B3DTex.flags |= 0x800
                
                if node.u_type == '0':
                    B3DTex.flags |= 0x10
                if node.u_type == '2':
                    B3DTex.flags |= 0x2000
                
                if node.v_type == '0':
                    B3DTex.flags |= 0x20
                if node.v_type == '2':
                    B3DTex.flags |= 0x4000
                
                if node.mapType == '1':
                    B3DTex.flags |= 0x40
                if node.mapType == '2':
                    B3DTex.flags |= 0x80
                
                TexsBlock.append(B3DTex)
        else:
            for node in mat.node_tree.nodes:
                if node.bl_idname == "ShaderNodeTexImage" and node.image != None:
                    B3DTex = TEXSBlock()
                    B3DTex.blenderTex = node
                    B3DTex.path = os.path.basename(node.image.filepath)
                    B3DTex.flags |= 1 | 8 # color + mipmap
                    
                    TexsBlock.append(B3DTex)
                
    return TexsBlock

def CreateBrus(obj,texs):
    BrusBlock = []
    for mat in obj.data.materials:
        currBrus = BRUSBlock()
        currBrus.mat_name = mat.name
        """tex = mat.node_tree.nodes.get("Image Texture")
        if tex:
            for i in range(0,len(texs)):
                btex = texs[i]
                if btex.blenderTex == tex:
                    currBrus.textures.append(i)"""
        # uhh, we need...a lot of custom data
        shaderNode = None
        for node in mat.node_tree.nodes:
            if node.bl_idname == "B3DShader":
                shaderNode = node
                break
        if shaderNode != None:
            from_socket_to_socket = dict([[link.from_socket, link.to_socket] for link in mat.node_tree.links])
            to_socket_from_socket = dict([[link.to_socket, link.from_socket] for link in mat.node_tree.links])
            texNodes = []
            firstTex = to_socket_from_socket.get(shaderNode.inputs[0],None)
            if (firstTex != None and firstTex.node.bl_idname == "B3DTextureInput"):
                texNodes.append(firstTex.node)
            for i in range(2,8):
                currTex = to_socket_from_socket.get(shaderNode.inputs[i],None)
                if (currTex != None and currTex.node.bl_idname == "B3DTextureInput"):
                    texNodes.append(currTex.node)
            currBrus.shiny = shaderNode.inputs[9].default_value
            currBrus.a = shaderNode.inputs[11].default_value
            currBrus.r = shaderNode.inputs[10].default_value[0]
            currBrus.g = shaderNode.inputs[10].default_value[1]
            currBrus.b = shaderNode.inputs[10].default_value[2]
            
            # append the textures
            for tex in texNodes:
                texImage = to_socket_from_socket.get(tex.inputs[0], None)
                if (texImage != None and texImage.node.bl_idname == "ShaderNodeTexImage"):
                    for i in range(0,len(texs)):
                        btex = texs[i]
                        if (btex.blenderTex == texImage.node):
                            currBrus.textures.append(i)
                            break
            
            currBrus.blend = int(shaderNode.blend_type)
            
            if shaderNode.inputs[13].default_value == True:
                currBrus.fx |= 1
            if shaderNode.inputs[14].default_value == True:
                currBrus.fx |= 4
            if shaderNode.inputs[15].default_value == False:
                currBrus.fx |= 8
            if shaderNode.inputs[16].default_value == True:
                currBrus.fx |= 0x10
            if shaderNode.inputs[17].default_value == True:
                currBrus.fx |= 0x2000
            
            # check for vertex colors
            vertColorNode = to_socket_from_socket.get(shaderNode.inputs[12], None)
            if (vertColorNode != None):
                print(vertColorNode.node.bl_idname)
            if vertColorNode != None and vertColorNode.node.bl_idname == "ShaderNodeVertexColor":
                currBrus.fx |= 2
            vertAlphaNode = to_socket_from_socket.get(shaderNode.inputs[18], None)
            if vertAlphaNode != None and vertAlphaNode.node.bl_idname == "ShaderNodeVertexColor":
                currBrus.fx |= 0x20
        else:
            # connect to the first texture found i guess
            for node in mat.node_tree.nodes:
                if node.bl_idname == "ShaderNodeTexImage":
                    for i in range(0,len(texs)):
                        if texs[i].blenderTex == node:
                            currBrus.textures.append(i)
                            break
                    break
            #raise Exception("Material doesn't have B3D Shader node!")
        BrusBlock.append(currBrus)
    return BrusBlock

def ConvertBoneList(nodes,vertGroups,workList):
    for bone in nodes:
        for v in vertGroups:
            if bone.name == v.name:
                workList[v.index] = bone
        ConvertBoneList(bone.subNodes,vertGroups,workList)

def CreateMesh(obj,boneNodes,vertexGroups,conv_coords):
    mesh = MESHBlock()
    mesh.vertBlock.tex_coord_count = len(obj.uv_layers)
    colors = None
    colorsAsFloat = True
    currVertCount = 0
    if len(obj.color_attributes) > 0:
        colors = obj.color_attributes[0]
        if (colors.data_type != "FLOAT_COLOR"):
            colorsAsFloat = False
        col = [0, 0, 0, 0] * len(colors.data)
        colors.data.foreach_get("color", col)
        if list(set(col)) == [1.0]:
            col = None
        
        if (colors.domain == "POINT"):
            # convert to corner
            newCol = []
            for face in obj.polygons:
                for loop_ind in range(face.loop_start, face.loop_start+3):
                    newCol.append(col[obj.loops[loop_ind].vertex_index*4])
                    newCol.append(col[(obj.loops[loop_ind].vertex_index*4)+1])
                    newCol.append(col[(obj.loops[loop_ind].vertex_index*4)+2])
                    newCol.append(col[(obj.loops[loop_ind].vertex_index*4)+3])
            col = newCol
        colors = col
    
    # convert vertex weight inds to weight inds as they're going to be written on export
    bone_conv_list = {}
    ConvertBoneList(boneNodes,vertexGroups,bone_conv_list)
    if (len(bone_conv_list) == 0):
        bone_conv_list = None
    
    for matId in range(0,len(obj.materials)):
        triBlock = TRISBlock()
        unoptimizedTris = []
        unoptimizedVerts = []
        triBlock.brushId = matId
        for face in obj.polygons:
            if face.material_index == matId:
                for loop_ind in range(face.loop_start, face.loop_start+3):
                    newVert = B3DVert()
                    loop = obj.loops[loop_ind]
                    newVert.x = obj.vertices[loop.vertex_index].undeformed_co.x
                    newVert.y = obj.vertices[loop.vertex_index].undeformed_co.y
                    newVert.z = obj.vertices[loop.vertex_index].undeformed_co.z
                    newVert.nx = loop.normal.x
                    newVert.ny = loop.normal.y
                    newVert.nz = loop.normal.z
                    if (conv_coords):
                        newVert.y = obj.vertices[loop.vertex_index].undeformed_co.z
                        newVert.z = -obj.vertices[loop.vertex_index].undeformed_co.y
                        newVert.ny = loop.normal.z
                        newVert.nz = -loop.normal.y
                    mag = math.sqrt((newVert.nx*newVert.nx)+(newVert.ny*newVert.ny)+(newVert.nz*newVert.nz))
                    newVert.nx /= mag
                    newVert.ny /= mag
                    newVert.nz /= mag
                    if colors != None:
                        newVert.r = colors[loop_ind*4]
                        newVert.g = colors[(loop_ind*4)+1]
                        newVert.b = colors[(loop_ind*4)+2]
                        newVert.a = colors[(loop_ind*4)+3]
                        if (colorsAsFloat == False):
                            newVert.r /= 255
                            newVert.g /= 255
                            newVert.b /= 255
                            newVert.a /= 255
                    if (bone_conv_list != None):
                        for g in obj.vertices[loop.vertex_index].groups:
                            if (bone_conv_list[g.group] != None):
                                newVert.weightInds.append(g.group)
                                newVert.weights.append(g.weight)
                    for uv_layer in obj.uv_layers:
                        uv = uv_layer.uv[loop_ind].vector
                        newVert.u.append(uv.x)
                        newVert.v.append(uv.y)
                    unoptimizedVerts.append(newVert)
                    unoptimizedTris.append(len(unoptimizedVerts)-1)
        
        # optimize vertex list
        i = 0
        while i < len(unoptimizedVerts):
            currVert = unoptimizedVerts[i]
            j = i+1
            while j < len(unoptimizedVerts):
                checkVert = unoptimizedVerts[j]
                if currVert.x == checkVert.x and currVert.y == checkVert.y and currVert.z == checkVert.z:
                    if currVert.nx == checkVert.nx and currVert.ny == checkVert.ny and currVert.nz == checkVert.nz:
                        if currVert.r == checkVert.r and currVert.g == checkVert.g and currVert.b == checkVert.b and currVert.a == checkVert.a:
                            validVert = True
                            for x in range(0,len(checkVert.u)):
                                if currVert.u[x] != checkVert.u[x] or currVert.v[x] != checkVert.v[x]:
                                    validVert = False
                                    break
                            if validVert == False:
                                j+=1
                                continue
                            for x in range(0,len(currVert.weightInds)):
                                if currVert.weightInds[x] != checkVert.weightInds[x] or currVert.weights[x] != checkVert.weights[x]:
                                    validVert = False
                                    break
                            if validVert == False:
                                j+=1
                                continue
                            # identical vertex located, remove it
                            unoptimizedVerts.pop(j)
                            for x in range(0,len(unoptimizedTris)):
                                if unoptimizedTris[x] == j:
                                    unoptimizedTris[x] = i
                                if unoptimizedTris[x] > j:
                                    unoptimizedTris[x] -= 1
                            j -= 1
                j += 1
            i += 1
        
        for i in range(0,len(unoptimizedTris)):
            unoptimizedTris[i] += currVertCount
        
        currVertCount += len(unoptimizedVerts)
        
        triBlock.tris = unoptimizedTris
        mesh.vertBlock.verts += unoptimizedVerts
        mesh.triBlocks.append(triBlock)
    # add vertices to bones
    if (bone_conv_list != None):
        for vind in range(0,len(mesh.vertBlock.verts)):
            vert = mesh.vertBlock.verts[vind]
            for i in range(0,len(vert.weightInds)):
                newWeight = BONEBlock()
                newWeight.vert = vind
                newWeight.weight = vert.weights[i]
                bone_conv_list[vert.weightInds[i]].bone.append(newWeight)
    if colors != None:
        mesh.vertBlock.flags |= 2
    return mesh

def CreateBone(bone,ind,conv_coords):
    retNode = NODEBlock()
    retNode.bone = []
    retNode.name = bone.name
    retNode.posX = bone.head.x
    retNode.posY = bone.head.y
    retNode.posZ = bone.head.z
    if (conv_coords):
        retNode.posY = bone.head.z
        retNode.posZ = -bone.head.y
    boneQuat = bone.matrix.to_quaternion()
    if (conv_coords):
        rotateQuat = mathutils.Euler((math.radians(-90),0,0), 'XYZ').to_quaternion()
        boneQuat = rotateQuat @ boneQuat
    retNode.rotW = boneQuat.w
    retNode.rotX = boneQuat.x
    retNode.rotY = boneQuat.y
    retNode.rotZ = boneQuat.z
    retNode.boneInd = ind
    ind += 1
    for childBone in bone.children:
        newBone,ind = CreateBone(childBone,ind,False) # don't recursively convert the coordinates! it'll curl up! only the bones without parents need conversion!
        retNode.subNodes.append(newBone)
    # TODO: animations
    return retNode,ind

def CreateNode(obj,parent,conv_coords):
    retNode = NODEBlock()
    retNode.name = obj.name
    if obj.type == 'MESH':
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object != None and parent == None: # sorry, we only support one skeleton
                CreateNode(mod.object,retNode)
        newmesh = obj.to_mesh(preserve_all_data_layers=True,depsgraph=bpy.context.evaluated_depsgraph_get())#obj.data.copy()
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.to_mesh(newmesh)
        bm.free()
        
        retNode.mesh = CreateMesh(newmesh,retNode.subNodes,obj.vertex_groups,conv_coords)
        
        retNode.posX = obj.location.x
        retNode.posY = obj.location.y
        retNode.posZ = obj.location.z
        if (conv_coords):
            retNode.posY = obj.location.z
            retNode.posZ = -obj.location.y
        retNode.scaleX = obj.scale.x
        retNode.scaleY = obj.scale.y
        retNode.scaleZ = obj.scale.z
        rotQuat = obj.rotation_euler.to_quaternion()
        retNode.rotW = rotQuat.w
        retNode.rotX = rotQuat.x
        retNode.rotY = rotQuat.y
        retNode.rotZ = rotQuat.z
    if obj.type == 'ARMATURE':
        boneInd = 0
        for bone in obj.data.bones:
            if bone.parent == None:
                newBone,boneInd = CreateBone(bone,boneInd,False) # coordinate conversion shouldn't be necessary on bones? as they're relative to the parent mesh?
                parent.subNodes.append(newBone)
    
    """for ob in obj.children:
        if ob != parent and (ob.type == 'MESH' or ob.type == 'ARMATURE'):
            retNode.subNodes.append(CreateNode(ob,obj))""" # sorry no support
    return retNode

def GetTexSize(texs):
    texSize = 0
    for tex in texs:
        texSize += len(tex.path)+1 # 0 terminator
        texSize += 0x1C
    return texSize

def GetBrusSize(brus):
    brusSize = 4
    for bru in brus:
        brusSize += 0x1C
        brusSize += 4 * 8 # texture count: idc i'm just making it 8 always
        brusSize += len(bru.mat_name) + 1
    return brusSize

def GetVertSize(vertBlock):
    vertSize = 0xC
    perVertSize = 0xC
    if (vertBlock.flags & 1) == 1:
        perVertSize += 0xC
    if (vertBlock.flags & 2) == 2:
        perVertSize += 0x10
    perVertSize += 4 * vertBlock.tex_coord_components * vertBlock.tex_coord_count
    vertSize += len(vertBlock.verts) * perVertSize
    return vertSize

def GetTriSize(triBlock):
    return 4 + (len(triBlock.tris)*4)

def GetMeshSize(mesh):
    meshSize = 4
    meshSize += 8 + GetVertSize(mesh.vertBlock)
    for triBlock in mesh.triBlocks:
        meshSize += 8 + GetTriSize(triBlock)
    
    return meshSize

def GetBoneSize(bone):
    return 8 * len(bone)

def GetNodeSize(node):
    nodeSize = len(node.name)+1
    nodeSize += 0x28
    for subNode in node.subNodes:
        nodeSize += 8 + GetNodeSize(subNode) # 8 to account for 4 byte magic and 4 byte length not factored in here
    
    if node.mesh != None:
        nodeSize += 8 + GetMeshSize(node.mesh)
    if (node.bone != None):
        nodeSize += 8 + GetBoneSize(node.bone)
    
    return nodeSize

def WriteTex(f,texs):
    WriteUInt8(f,0x54)
    WriteUInt8(f,0x45)
    WriteUInt8(f,0x58)
    WriteUInt8(f,0x53)
    WriteUInt32(f,GetTexSize(texs))
    for tex in texs:
        WriteString(f,tex.path)
        WriteUInt32(f,tex.flags)
        WriteUInt32(f,tex.blend)
        WriteFloat(f,tex.x_offs)
        WriteFloat(f,tex.y_offs)
        WriteFloat(f,tex.x_scale)
        WriteFloat(f,tex.y_scale)
        WriteFloat(f,tex.rotation)

def WriteBrus(f, brus):
    WriteUInt8(f,0x42)
    WriteUInt8(f,0x52)
    WriteUInt8(f,0x55)
    WriteUInt8(f,0x53)
    WriteUInt32(f,GetBrusSize(brus))
    WriteUInt32(f,8)
    for bru in brus:
        WriteString(f,bru.mat_name)
        WriteFloat(f,bru.r)
        WriteFloat(f,bru.g)
        WriteFloat(f,bru.b)
        alpha = bru.a
        if alpha > 1:
            alpha = 1
        if alpha < 0:
            alpha = 0
        WriteFloat(f,alpha)
        shiny = bru.shiny
        if shiny > 1:
            shiny = 1
        if shiny < 0:
            shiny = 0
        WriteFloat(f,shiny)
        WriteUInt32(f,bru.blend)
        WriteUInt32(f,bru.fx)
        i = 0
        while i < 8:
            if i < len(bru.textures):
                WriteUInt32(f,bru.textures[i])
            else:
                WriteInt32(f,-1)
            i += 1

def WriteVerts(f,verts):
    WriteUInt8(f,0x56)
    WriteUInt8(f,0x52)
    WriteUInt8(f,0x54)
    WriteUInt8(f,0x53)
    WriteUInt32(f,GetVertSize(verts))
    WriteUInt32(f,verts.flags)
    WriteUInt32(f,verts.tex_coord_count)
    WriteUInt32(f,verts.tex_coord_components)
    for v in verts.verts:
        WriteFloat(f,v.x)
        WriteFloat(f,v.y)
        WriteFloat(f,v.z)
        if (verts.flags & 1) != 0:
            WriteFloat(f,v.nx)
            WriteFloat(f,v.ny)
            WriteFloat(f,v.nz)
        if (verts.flags & 2) != 0:
            WriteFloat(f,v.r)
            WriteFloat(f,v.g)
            WriteFloat(f,v.b)
            WriteFloat(f,v.a)
        for i in range(0,verts.tex_coord_count):
            WriteFloat(f,v.u[i])
            WriteFloat(f,1-v.v[i])

def WriteTris(f,tris):
    WriteUInt8(f,0x54)
    WriteUInt8(f,0x52)
    WriteUInt8(f,0x49)
    WriteUInt8(f,0x53)
    WriteUInt32(f,GetTriSize(tris))
    WriteUInt32(f,tris.brushId)
    for t in tris.tris:
        WriteUInt32(f,t)

def WriteMesh(f,mesh):
    WriteUInt8(f,0x4D)
    WriteUInt8(f,0x45)
    WriteUInt8(f,0x53)
    WriteUInt8(f,0x48)
    WriteUInt32(f,GetMeshSize(mesh))
    WriteInt32(f,mesh.brushId)
    WriteVerts(f,mesh.vertBlock)
    for x in mesh.triBlocks:
        WriteTris(f,x)

def WriteBone(f,bone):
    WriteUInt8(f,0x42)
    WriteUInt8(f,0x4F)
    WriteUInt8(f,0x4E)
    WriteUInt8(f,0x45)
    WriteUInt32(f,GetBoneSize(bone))
    for i in range(0,len(bone)):
        WriteUInt32(f,bone[i].vert)
        WriteFloat(f,bone[i].weight)

def WriteNode(f,node):
    WriteUInt8(f,0x4E)
    WriteUInt8(f,0x4F)
    WriteUInt8(f,0x44)
    WriteUInt8(f,0x45)
    WriteUInt32(f,GetNodeSize(node))
    WriteString(f,node.name)
    WriteFloat(f,node.posX)
    WriteFloat(f,node.posY)
    WriteFloat(f,node.posZ)
    WriteFloat(f,node.scaleX)
    WriteFloat(f,node.scaleY)
    WriteFloat(f,node.scaleZ)
    WriteFloat(f,node.rotW)
    WriteFloat(f,node.rotX)
    WriteFloat(f,node.rotY)
    WriteFloat(f,node.rotZ)
    if node.mesh != None:
        WriteMesh(f,node.mesh)
    if node.bone != None:
        WriteBone(f,node.bone)
    
    for subNode in node.subNodes:
        WriteNode(f,subNode)

def WriteFile(texs,brus,node,filepath):
    f = open(filepath,'wb')
    
    WriteUInt8(f,0x42) # BB3D
    WriteUInt8(f,0x42)
    WriteUInt8(f,0x33)
    WriteUInt8(f,0x44)
    
    texSize = GetTexSize(texs)
    brusSize = GetBrusSize(brus)
    nodeSize = GetNodeSize(node)
    # TEXS is optional...
    if (texSize == 0):
        texSize = -8
    WriteUInt32(f,texSize+brusSize+nodeSize+0x18+4)
    
    WriteUInt32(f,1)
    
    if (texSize > 0):
        WriteTex(f,texs)
    WriteBrus(f,brus)
    WriteNode(f,node)
    
    f.close()

def b3d_export(filepath,conv_coords,combine_all):
    # need current object...
    curr_obj = bpy.context.active_object
    if (combine_all):
        curr_mesh = bpy.data.meshes.new("mesh")
        curr_obj = bpy.data.objects.new("TempMesh", curr_mesh)
        bpy.context.collection.objects.link(curr_obj)
        new_objs = []
        for ob in bpy.context.selected_objects:
            if (ob.type == 'MESH'):
                new_mesh = ob.data.copy()
                new_obj = ob.copy()
                new_obj.data = new_mesh
                bpy.context.collection.objects.link(new_obj)
                new_objs.append(new_obj)
            ob.select_set(False)
        for ob in new_objs:
            # iterate again to apply modifiers
            bpy.context.view_layer.objects.active = ob
            ob.select_set(True)
            bpy.ops.object.make_single_user(object=True,obdata=True,material=True,animation=False,obdata_animation=False)
            for modifier in ob.modifiers:
                bpy.ops.object.modifier_apply(modifier=modifier.name)
        curr_obj.select_set(True)
        bpy.context.view_layer.objects.active = curr_obj
        bpy.ops.object.join()
    if (curr_obj == None):
        return {'CANCELLED'}
    if (curr_obj.type != 'MESH'):
        return {'CANCELLED'}
    if (len(curr_obj.data.materials) == 0):
        return {'CANCELLED'}
    
    texs = CreateTexs(curr_obj)
    brus = CreateBrus(curr_obj,texs)
    node = CreateNode(curr_obj,None,conv_coords)
    
    WriteFile(texs,brus,node,filepath)
    
    if (combine_all):
        bpy.ops.object.delete()
    
    return {"FINISHED"}

def menu_func_export(self, context):
    self.layout.operator(ExportB3D.bl_idname, text="B3D Model Export (.B3D)")

def register():
    bpy.utils.register_class(ExportB3D)
    bpy.utils.register_class(B3DNodeAdd)
    bpy.utils.register_class(B3D_MT_Node_Add)
    bpy.utils.register_class(ShaderNodeB3DTexture)
    bpy.utils.register_class(ShaderNodeB3D)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    bpy.types.NODE_MT_add.append(b3d_node_menu)

def unregister():
    bpy.utils.unregister_class(ExportB3D)
    bpy.utils.unregister_class(B3DNodeAdd)
    bpy.utils.unregister_class(B3D_MT_Node_Add)
    bpy.utils.unregister_class(ShaderNodeB3DTexture)
    bpy.utils.unregister_class(ShaderNodeB3D)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.NODE_MT_add.remove(b3d_node_menu)



class B3DNodeAdd(bpy.types.Operator):
    """Spawn in an NN node"""
    bl_idname = "node.add_node_b3d"
    bl_label = "Node Add B3D Operator"

    use_transform: BoolProperty(
    )

    type: StringProperty(
    )

    @classmethod
    def poll(cls, context):
        return context.area.ui_type == 'ShaderNodeTree'

    def execute(self, context):
        MakeGroups().execute()
        bpy.ops.node.add_node(use_transform=self.use_transform, type=self.type)
        return {'FINISHED'}


class B3D_MT_Node_Add(bpy.types.Menu):
    bl_label = "B3D"

    def draw(self, context):
        layout = self.layout
        classes = []
        classes.append(ShaderNodeB3DTexture)
        classes.append(ShaderNodeB3D)
        for cla in classes:
            var = layout.operator("node.add_node_b3d", text=cla.bl_label)
            var.type = cla.bl_idname
            var.use_transform = True


def b3d_node_menu(self, context):
    if context.area.ui_type == 'ShaderNodeTree':
        layout = self.layout
        layout.separator()
        layout.menu("B3D_MT_Node_Add")

class CustomNodetreeNodeBaseNN:
    def copy(self, node):
        self.node_tree = node.node_tree.copy()

    def free(self):
        pass

    def draw_buttons(self, context, layout):
        for prop in self.bl_rna.properties:
            if prop.is_runtime and not prop.is_readonly:
                if prop.type == "ENUM":
                    text = ""
                else:
                    text = prop.name
                layout.prop(self, prop.identifier, text=text)


# big thanks to arg!! for helping me with the node stuff!
class ShaderNodeB3DTexture(CustomNodetreeNodeBaseNN, ShaderNodeCustomGroup):
    bl_label = "B3D Texture Input"
    bl_idname = "B3DTextureInput"
    bl_width_default = 180

    def u_types(self, context):
        wrap_types = (
            ('0', "Clamp U", ""),
            ('1', "Repeat U", ""),
            ('2', "Mirror U", ""),
        )
        return wrap_types

    def v_types(self, context):
        wrap_types = (
            ('0', "Clamp V", ""),
            ('1', "Repeat V", ""),
            ('2', "Mirror V", ""),
        )
        return wrap_types
    
    def mapTypes(self, context):
        sample_types = (
            ('0', "Standard", ""),
            ('1', "Sphere", ""),
            ('2', "Cube", ""),
        )
        return sample_types
    
    def blendTypes(self, context):
        blendtypes = (
            ('0', "Replace", ""),
            ('1', "Alpha", ""),
            ('2', "Multiply", ""),
            ('3', "Additive", ""),
            ('4', "Dot3", ""),
            ('5', "Multiply2", ""),
        )
        return blendtypes

    def copy(self, node):
        self.node_tree = node.node_tree

    def free(self):
        pass  # defining this so blender doesn't try to remove the group

    u_type: EnumProperty(name="U Wrapping", items=u_types)
    v_type: EnumProperty(name="V Wrapping", items=v_types)
    mapType: EnumProperty(name="Mapping type", items=mapTypes)
    blend_type: EnumProperty(name="Blend type", items=blendTypes)

    def init(self, context):
        self.node_tree = bpy.data.node_groups['_B3D_TEX']
        self.u_type = self.u_types(context)[1][0]
        self.v_type = self.v_types(context)[1][0]
        self.mapType = self.mapTypes(context)[0][0]
        self.blend_type = self.blendTypes(context)[2][0]

class ShaderNodeB3D(CustomNodetreeNodeBaseNN, ShaderNodeCustomGroup):
    bl_label = "B3D Shader"
    bl_idname = "B3DShader"
    bl_width_default = 180
    
    def blendTypes(self, context):
        blendtypes = (
            ('1', "Alpha", ""),
            ('2', "Multiply", ""),
            ('3', "Additive", ""),
        )
        return blendtypes

    def copy(self, node):
        self.node_tree = node.node_tree

    def free(self):
        pass  # defining this so blender doesn't try to remove the group

    blend_type: EnumProperty(name="Blend type", items=blendTypes)

    def init(self, context):
        self.node_tree = bpy.data.node_groups['_B3D_NODE']
        self.blend_type = self.blendTypes(context)[0][0]

class MakeGroups:
    def execute(self):
        if '_B3D_NODE' in bpy.data.node_groups:
            return
        self.B3DGroup()
        self.B3DTexNode()
    
    @staticmethod
    def B3DTexNode():
        tree = bpy.data.node_groups.new('_B3D_TEX', 'ShaderNodeTree')
        tree.use_fake_user = True

        # Group inputs
        var = tree.interface.new_socket(name='Texture',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (1.0,1.0,1.0, 1.0)

        var = tree.interface.new_socket(name='Color',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = True

        var = tree.interface.new_socket(name='Alpha',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = False

        var = tree.interface.new_socket(name='AlphaMask',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = False

        var = tree.interface.new_socket(name='MipMap',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = True

        var = tree.interface.new_socket(name='UV2',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = False

        var = tree.interface.new_socket(name='NearestNeighbor',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = False

        # Group outputs
        var = tree.interface.new_socket(name='Color',  in_out='OUTPUT', socket_type='NodeSocketColor')
        var.hide_value = False
        var.default_value = (0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0)

        # Group Nodes
        var = tree.nodes.new(type='NodeGroupInput')
        var.name = 'Group Input'
        var.location = (-594.6561279296875, -165.0909881591797)

        var = tree.nodes.new(type='NodeGroupOutput')
        var.name = 'Group Output'
        var.location = (145.34390258789062, -165.0909881591797)
        var.inputs[0].default_value = (0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0)
        var.is_active_output = True

        var = tree.nodes.new(type='ShaderNodeMix')
        var.name = 'Mix'
        var.location = (-431.2869567871094, -326.372314453125)
        var.inputs[0].default_value = 0.5
        var.inputs[1].default_value = (0.5, 0.5, 0.5)
        var.inputs[2].default_value = 0.0
        var.inputs[3].default_value = 0.0
        var.inputs[4].default_value = (0.0, 0.0, 0.0)
        var.inputs[5].default_value = (0.0, 0.0, 0.0)
        var.inputs[6].default_value = (0.5, 0.5, 0.5, 1.0)
        var.inputs[7].default_value = (0.0, 0.0, 0.0, 0.0)
        var.factor_mode = 'UNIFORM'
        var.clamp_result = False
        var.data_type = 'RGBA'
        var.blend_type = 'ADD'
        var.clamp_factor = True

        # Group Node links
        tree.links.new(tree.nodes["Group Input"].outputs[0], tree.nodes["Group Output"].inputs[0])

    
    @staticmethod
    def B3DGroup():
        tree = bpy.data.node_groups.new('_B3D_NODE', 'ShaderNodeTree')
        tree.use_fake_user = True

        # Group inputs
        var = tree.interface.new_socket(name='Texture1',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0)

        var = tree.interface.new_socket(name='Texture1Alpha',  in_out='INPUT', socket_type='NodeSocketFloat')
        var.min_value = -3.4028234663852886e+38
        var.max_value = 3.4028234663852886e+38
        var.hide_value = True
        var.default_value = 1.0

        var = tree.interface.new_socket(name='Texture2',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (0.0, 0.0, 0.0, 1.0)

        var = tree.interface.new_socket(name='Texture3',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (0.0, 0.0, 0.0, 1.0)

        var = tree.interface.new_socket(name='Texture4',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (0.0, 0.0, 0.0, 1.0)

        var = tree.interface.new_socket(name='Texture5',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (0.0, 0.0, 0.0, 1.0)

        var = tree.interface.new_socket(name='Texture6',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (0.0, 0.0, 0.0, 1.0)

        var = tree.interface.new_socket(name='Texture7',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (0.0, 0.0, 0.0, 1.0)

        var = tree.interface.new_socket(name='Texture8',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (0.0, 0.0, 0.0, 1.0)

        var = tree.interface.new_socket(name='Specular',  in_out='INPUT', socket_type='NodeSocketFloat')
        var.min_value = 0
        var.max_value = 1.0
        var.hide_value = False
        var.default_value = 0.0

        var = tree.interface.new_socket(name='Color',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = False
        var.default_value = (1.0, 1.0, 1.0, 1.0)

        var = tree.interface.new_socket(name='Alpha',  in_out='INPUT', socket_type='NodeSocketFloat')
        var.min_value = 0
        var.max_value = 1.0
        var.hide_value = False
        var.default_value = 1.0

        var = tree.interface.new_socket(name='VertexColor',  in_out='INPUT', socket_type='NodeSocketColor')
        var.hide_value = True
        var.default_value = (1.0, 1.0, 1.0, 1.0)

        var = tree.interface.new_socket(name='FullBright',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = False

        var = tree.interface.new_socket(name='FlatShading',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = False

        var = tree.interface.new_socket(name='Fog',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = True

        var = tree.interface.new_socket(name='DoubleSided',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = False

        var = tree.interface.new_socket(name='AlphaMask',  in_out='INPUT', socket_type='NodeSocketBool')
        var.hide_value = False
        var.default_value = False

        var = tree.interface.new_socket(name='VertexAlpha',  in_out='INPUT', socket_type='NodeSocketFloat')
        var.min_value = -3.4028234663852886e+38
        var.max_value = 3.4028234663852886e+38
        var.hide_value = True
        var.default_value = 1.0

        # Group outputs
        var = tree.interface.new_socket(name='BSDF',  in_out='OUTPUT', socket_type='NodeSocketShader')
        var.hide_value = False

        # Group Nodes
        var = tree.nodes.new(type='NodeGroupInput')
        var.name = 'Group Input'
        var.location = (-875.4047241210938, 157.26438903808594)

        var = tree.nodes.new(type='NodeGroupOutput')
        var.name = 'Group Output'
        var.location = (300.0, 0.0)
        var.is_active_output = True

        var = tree.nodes.new(type='ShaderNodeEeveeSpecular')
        var.name = 'Specular BSDF'
        var.location = (-70.0, 0.0)
        var.inputs[0].default_value = (0.800000011920929, 0.800000011920929, 0.800000011920929, 1.0)
        var.inputs[1].default_value = (0.029999999329447746, 0.029999999329447746, 0.029999999329447746, 1.0)
        var.inputs[2].default_value = 0.20000000298023224
        var.inputs[3].default_value = (0.0, 0.0, 0.0, 1.0)
        var.inputs[4].default_value = 0.0
        var.inputs[5].default_value = (0.0, 0.0, 0.0)
        var.inputs[6].default_value = 0.0
        var.inputs[7].default_value = 0.0
        var.inputs[8].default_value = (0.0, 0.0, 0.0)
        var.inputs[9].default_value = 0.0

        var = tree.nodes.new(type='ShaderNodeMath')
        var.name = 'Math'
        var.location = (-233.51634216308594, -163.1317138671875)
        var.inputs[0].default_value = 1.0
        var.inputs[1].default_value = 0.5
        var.inputs[2].default_value = 0.5
        var.operation = 'SUBTRACT'
        var.use_clamp = False

        var = tree.nodes.new(type='ShaderNodeMix')
        var.name = 'Mix'
        var.location = (-486.3960876464844, 255.9084014892578)
        var.inputs[0].default_value = 1.0
        var.inputs[1].default_value = (0.5, 0.5, 0.5)
        var.inputs[2].default_value = 0.0
        var.inputs[3].default_value = 0.0
        var.inputs[4].default_value = (0.0, 0.0, 0.0)
        var.inputs[5].default_value = (0.0, 0.0, 0.0)
        var.inputs[6].default_value = (0.5, 0.5, 0.5, 1.0)
        var.inputs[7].default_value = (0.5, 0.5, 0.5, 1.0)
        var.factor_mode = 'UNIFORM'
        var.clamp_result = False
        var.data_type = 'RGBA'
        var.blend_type = 'MULTIPLY'
        var.clamp_factor = True

        var = tree.nodes.new(type='ShaderNodeMix')
        var.name = 'Mix.001'
        var.location = (-252.66357421875, 241.39598083496094)
        var.inputs[0].default_value = 1.0
        var.inputs[1].default_value = (0.5, 0.5, 0.5)
        var.inputs[2].default_value = 0.0
        var.inputs[3].default_value = 0.0
        var.inputs[4].default_value = (0.0, 0.0, 0.0)
        var.inputs[5].default_value = (0.0, 0.0, 0.0)
        var.inputs[6].default_value = (0.5, 0.5, 0.5, 1.0)
        var.inputs[7].default_value = (0.5, 0.5, 0.5, 1.0)
        var.factor_mode = 'UNIFORM'
        var.clamp_result = False
        var.data_type = 'RGBA'
        var.blend_type = 'MULTIPLY'
        var.clamp_factor = True

        var = tree.nodes.new(type='ShaderNodeMath')
        var.name = 'Math.001'
        var.location = (-632.1868896484375, -295.4994812011719)
        var.inputs[0].default_value = 0.5
        var.inputs[1].default_value = 0.5
        var.inputs[2].default_value = 0.5
        var.operation = 'MULTIPLY'
        var.use_clamp = False

        var = tree.nodes.new(type='ShaderNodeMath')
        var.name = 'Math.002'
        var.location = (-439.9339599609375, -224.37693786621094)
        var.inputs[0].default_value = 0.5
        var.inputs[1].default_value = 0.5
        var.inputs[2].default_value = 0.5
        var.operation = 'MULTIPLY'
        var.use_clamp = False

        # Group Node links
        tree.links.new(tree.nodes["Group Input"].outputs[9], tree.nodes["Specular BSDF"].inputs[1])
        tree.links.new(tree.nodes["Math"].outputs[0], tree.nodes["Specular BSDF"].inputs[4])
        tree.links.new(tree.nodes["Specular BSDF"].outputs[0], tree.nodes["Group Output"].inputs[0])
        tree.links.new(tree.nodes["Group Input"].outputs[0], tree.nodes["Mix"].inputs[6])
        tree.links.new(tree.nodes["Group Input"].outputs[10], tree.nodes["Mix"].inputs[7])
        tree.links.new(tree.nodes["Mix.001"].outputs[2], tree.nodes["Specular BSDF"].inputs[0])
        tree.links.new(tree.nodes["Mix"].outputs[2], tree.nodes["Mix.001"].inputs[6])
        tree.links.new(tree.nodes["Group Input"].outputs[12], tree.nodes["Mix.001"].inputs[7])
        tree.links.new(tree.nodes["Group Input"].outputs[18], tree.nodes["Math.001"].inputs[0])
        tree.links.new(tree.nodes["Group Input"].outputs[11], tree.nodes["Math.001"].inputs[1])
        tree.links.new(tree.nodes["Math.002"].outputs[0], tree.nodes["Math"].inputs[1])
        tree.links.new(tree.nodes["Math.001"].outputs[0], tree.nodes["Math.002"].inputs[0])
        tree.links.new(tree.nodes["Group Input"].outputs[1], tree.nodes["Math.002"].inputs[1])


@persistent
def make_node_groups(scene):
    MakeGroups().execute()

bpy.app.handlers.load_post.append(make_node_groups)

if __name__ == "__main__":
    register()
    MakeGroups().execute()
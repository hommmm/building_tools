import math
import bmesh
import operator
import mathutils
from mathutils import Vector
from bmesh.types import BMVert, BMEdge, BMFace
from ...utils import equal, select, skeletonize, filter_geom, calc_edge_median


def create_roof(bm, faces, prop):
    """Create different roof types

    Args:
        bm (bmesh.types.BMesh): bmesh from current edit mesh
        faces (bmesh.types.BMFace): list of user selected faces
        type (str): type of roof to generate as defined in RoofProperty
        **kwargs: Extra kargs from RoofProperty
    """
    select(faces, False)
    if prop.type == "FLAT":
        create_flat_roof(bm, faces, prop)
    elif prop.type == "GABLE":
        create_gable_roof(bm, faces, prop)
    elif prop.type == "HIP":
        create_hip_roof(bm, faces, prop)


def create_flat_roof(bm, faces, prop):
    """Create a basic flat roof

    Args:
        bm (bmesh.types.BMesh): bmesh from current edit mesh
        faces (bmesh.types.BMFace): list of user selected faces

    Returns:
        list(bmesh.types.BMFace): Resulting top face
    """
    ret = bmesh.ops.extrude_face_region(bm, geom=faces)
    bmesh.ops.translate(
        bm, vec=(0, 0, prop.thickness), verts=filter_geom(ret["geom"], BMVert)
    )

    top_face = filter_geom(ret["geom"], BMFace)[-1]
    link_faces = [f for e in top_face.edges for f in e.link_faces if f is not top_face]

    bmesh.ops.inset_region(
        bm, faces=link_faces, depth=prop.outset, use_even_offset=True
    )
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.delete(bm, geom=faces, context="FACES")

    new_faces = list({f for e in top_face.edges for f in e.link_faces})
    return bmesh.ops.dissolve_faces(bm, faces=new_faces).get("region")


def create_gable_roof(bm, faces, prop):
    """Create a gable roof

    Args:
        bm (bmesh.types.BMesh): bmesh from current edit mesh
        faces (bmesh.types.BMFace): list of user selected faces
    """
    if not is_rectangular(faces):
        return

    axis = "x" if prop.orient == "HORIZONTAL" else "y"
    if len(faces) > 1:
        faces = bmesh.ops.dissolve_faces(bm, faces=faces, use_verts=True).get("region")

    edges = extrude_up_and_delete_faces(bm, faces, prop.height)
    merge_verts_along_axis(bm, set(v for e in edges for v in e.verts), axis)

    roof_faces = get_highest_z_facing_faces(bm)
    boundary_edges = [
        e for f in roof_faces for e in f.edges if e.calc_face_angle(1000.0) < math.pi
    ]
    bmesh.ops.delete(bm, geom=roof_faces, context="FACES")

    hang_edges = create_roof_hangs(bm, boundary_edges, prop.outset)
    fill_roof_faces_from_hang(bm, hang_edges, prop.thickness, axis)


def create_hip_roof(bm, faces, prop):
    """Create a hip roof

    Args:
        bm (bmesh.types.BMesh): bmesh from current edit mesh
        faces (bmesh.types.BMFace): list of user selected faces
    """
    faces = create_flat_roof(bm, faces, prop)
    face = faces[-1]
    median = face.calc_center_median()

    # get verts in anti-clockwise order
    original_edges = [e for e in face.edges]
    verts = [v for v in sort_verts_by_loops(face)]
    points = [v.co.to_tuple()[:2] for v in verts]

    # compute skeleton
    skeleton = skeletonize(points, [])
    bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")

    height_scale = prop.height / max([arc.height for arc in skeleton])

    # 3. -- create edges and vertices
    skeleton_edges = create_hiproof_verts_and_edges(
        bm, skeleton, original_edges, median, height_scale
    )

    # 4. -- create faces
    create_hiproof_faces(bm, original_edges, skeleton_edges)


def is_rectangular(faces):
    """ Determine if faces form a recatngular area """
    # TODO - using area to determine this can fail, better
    # have checks to determine if verts are only horizontally
    # and vertically aligned.

    face_area = sum([f.calc_area() for f in faces])

    verts = [v for f in faces for v in f.verts]
    verts = sorted(verts, key=lambda v: (v.co.x, v.co.y))

    _min, _max = verts[0], verts[-1]
    width = abs(_min.co.x - _max.co.x)
    length = abs(_min.co.y - _max.co.y)
    area = width * length

    if round(face_area, 4) == round(area, 4):
        return True
    return False


def sort_verts_by_loops(face):
    """ sort verts in face clockwise using loops """

    start_loop = max(face.loops, key=lambda loop: loop.vert.co.to_tuple()[:2])

    verts = []
    current_loop = start_loop
    while len(verts) < len(face.loops):
        verts.append(current_loop.vert)
        current_loop = current_loop.link_loop_prev

    return verts


def vert_at_loc(loc, verts, loc_z=None):
    """ Find all verts at loc(x,y), return the one with highest z coord """

    results = []
    for vert in verts:
        co = vert.co
        if equal(co.x, loc.x) and equal(co.y, loc.y):
            if loc_z:
                if equal(co.z, loc_z):
                    results.append(vert)
            else:
                results.append(vert)

    if results:
        return max([v for v in results], key=lambda v: v.co.z)
    return None


def extrude_up_and_delete_faces(bm, faces, extrude_depth):
    ret = bmesh.ops.extrude_face_region(bm, geom=faces)
    verts = filter_geom(ret["geom"], BMVert)
    edges = filter_geom(ret["geom"], BMEdge)
    nfaces = filter_geom(ret["geom"], BMFace)
    bmesh.ops.translate(bm, verts=verts, vec=(0, 0, extrude_depth))
    bmesh.ops.delete(bm, geom=faces + nfaces, context="FACES_ONLY")
    return edges


def merge_verts_along_axis(bm, verts, axis):
    key_func = operator.attrgetter("co." + axis)
    _max = max(verts, key=key_func)
    _min = min(verts, key=key_func)
    mid = getattr((_max.co + _min.co) / 2, axis)
    for v in verts:
        setattr(v.co, axis, mid)
    bmesh.ops.remove_doubles(bm, verts=bm.verts)


def get_highest_z_facing_faces(bm):
    maxz = max([v.co.z for v in bm.verts])
    top_verts = [v for v in bm.verts if v.co.z == maxz]
    return list(set([f for v in top_verts for f in v.link_faces if f.normal.z]))


def create_roof_hangs(bm, edges, size):
    ret = bmesh.ops.extrude_edge_only(bm, edges=edges)
    verts = filter_geom(ret["geom"], BMVert)
    bmesh.ops.scale(bm, verts=verts, vec=(1 + size, 1 + size, 1))
    hang_edges = list(
        {e for v in verts for e in v.link_edges if all([v in verts for v in e.verts])}
    )

    # -- fix roof slope at bottom edges
    min_loc_z = min([v.co.z for e in hang_edges for v in e.verts])
    min_verts = list({v for e in hang_edges for v in e.verts if v.co.z == min_loc_z})
    bmesh.ops.translate(bm, verts=min_verts, vec=(0, 0, -size))
    return hang_edges


def fill_roof_faces_from_hang(bm, edges, roof_thickness, axis):
    # -- extrude edges upwards and fill face
    ret = bmesh.ops.extrude_edge_only(bm, edges=edges)
    verts = filter_geom(ret["geom"], BMVert)
    edges = filter_geom(ret["geom"], BMEdge)
    bmesh.ops.translate(bm, verts=verts, vec=(0, 0, roof_thickness))

    valid_edges = [
        e
        for e in edges
        if calc_edge_median(e).z != min([v.co.z for e in edges for v in e.verts])
    ]
    edge_loc = set([getattr(calc_edge_median(e), axis) for e in valid_edges])

    # -- fill faces
    for loc in edge_loc:
        edges = [e for e in valid_edges if getattr(calc_edge_median(e), axis) == loc]
        bmesh.ops.contextual_create(bm, geom=edges)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)


def create_hiproof_verts_and_edges(bm, skeleton, original_edges, median, height_scale):
    skeleton_edges = []
    skeleton_verts = []
    for arc in skeleton:
        source = arc.source
        vsource = vert_at_loc(source, bm.verts)
        if not vsource:
            ht = (
                height_scale
                * [arc.height for arc in skeleton if arc.source == source][-1]
            )
            vsource = make_vert(bm, Vector((source.x, source.y, median.z + ht)))
            skeleton_verts.append(vsource)

        for sink in arc.sinks:
            # -- create sink vert
            vs = vert_at_loc(sink, bm.verts)
            if not vs:
                ht = height_scale * min(
                    [arc.height for arc in skeleton if sink in arc.sinks]
                )
                vs = make_vert(bm, Vector((sink.x, sink.y, median.z + ht)))
            skeleton_verts.append(vs)

            # create edge
            if vs != vsource:
                geom = bmesh.ops.contextual_create(bm, geom=[vsource, vs]).get("edges")
                skeleton_edges.extend(geom)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

    skeleton_verts = [
        v
        for v in skeleton_verts
        if v in {v for e in skeleton_edges for v in e.verts}
        and v not in {v for e in original_edges for v in e.verts}
    ]
    new_verts = join_intersecting_verts_and_edges(bm, skeleton_edges, skeleton_verts)
    skeleton_verts = list(filter(lambda v: v.is_valid, skeleton_verts)) + new_verts
    skeleton_edges = list(set(e for v in skeleton_verts for e in v.link_edges))
    return skeleton_edges


def create_hiproof_faces(bm, original_edges, skeleton_edges):
    for ed in original_edges:
        verts = ed.verts
        linked_skeleton_edges = get_linked_edges(verts, skeleton_edges)

        if len(linked_skeleton_edges) == 0:
            linked_original = get_linked_edges(verts, original_edges)
            verts = [v for e in linked_original for v in e.verts if v not in verts]
            linked_skeleton_edges = get_linked_edges(verts, skeleton_edges)
        elif len(linked_skeleton_edges) == 1:
            continue

        all_verts = [v for e in linked_skeleton_edges for v in e.verts]
        opposite_verts = list(set(all_verts) - set(verts))

        if len(opposite_verts) == 1:
            # -- found triangle face
            bmesh.ops.contextual_create(bm, geom=linked_skeleton_edges + [ed])
        else:
            edge = bm.edges.get(opposite_verts)
            if edge:
                # -- found quad
                geometry = linked_skeleton_edges + [ed, edge]
                bmesh.ops.contextual_create(bm, geom=geometry)
            else:
                v1, v2 = opposite_verts
                next_skeleton_edges = list(
                    set(skeleton_edges) - set(linked_skeleton_edges)
                )
                v1_edges = get_linked_edges([v1], next_skeleton_edges)
                v2_edges = get_linked_edges([v2], next_skeleton_edges)
                pair = find_closest_pair_edges(v1_edges, v2_edges)

                all_verts = [v for e in pair for v in e.verts]
                opposite_verts = list(set(all_verts) - set(opposite_verts))
                if len(opposite_verts) == 1:
                    geometry = [ed] + linked_skeleton_edges + list(pair)
                    bmesh.ops.contextual_create(bm, geom=geometry)
                else:
                    edge = bm.edges.get(opposite_verts)
                    if edge:
                        geometry = list(pair) + linked_skeleton_edges + [ed, edge]
                        bmesh.ops.contextual_create(bm, geom=geometry)
                    else:
                        v1, v2 = opposite_verts
                        next_skeleton_edges = list(
                            set(next_skeleton_edges)
                            - set(linked_skeleton_edges + list(pair))
                        )
                        v1_edges = get_linked_edges([v1], next_skeleton_edges)
                        v2_edges = get_linked_edges([v2], next_skeleton_edges)
                        pair2 = find_closest_pair_edges(v1_edges, v2_edges)

                        all_verts = [v for e in pair2 for v in e.verts]
                        opposite_verts = list(set(all_verts) - set(opposite_verts))
                        if len(opposite_verts) == 1:
                            geometry = [ed] + linked_skeleton_edges + list(pair + pair2)
                            bmesh.ops.contextual_create(bm, geom=geometry)


def make_vert(bm, location):
    return bmesh.ops.create_vert(bm, co=location).get("vert")[-1]


def join_intersecting_verts_and_edges(bm, edges, verts):
    new_verts = []
    for v in verts:
        for e in edges:
            if v in e.verts:
                continue

            v1, v2 = e.verts
            res = mathutils.geometry.intersect_line_line_2d(v.co, v.co, v1.co, v2.co)
            if res is not None:
                split_vert = v1
                split_factor = (v1.co - v.co).length / e.calc_length()
                new_edge, new_vert = bmesh.utils.edge_split(e, split_vert, split_factor)
                new_verts.append(new_vert)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.01)
    return list(filter(lambda v: v.is_valid, new_verts))


def get_linked_edges(verts, filter_edges):
    linked_edges = [e for v in verts for e in v.link_edges]
    return list(filter(lambda e: e in filter_edges, linked_edges))


def find_closest_pair_edges(edges_a, edges_b):
    def length_func(pair):
        e1, e2 = pair
        return (calc_edge_median(e1) - calc_edge_median(e2)).length

    pairs = [(e1, e2) for e1 in edges_a for e2 in edges_b]
    return sorted(pairs, key=length_func)[0]

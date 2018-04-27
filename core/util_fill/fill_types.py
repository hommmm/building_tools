import bmesh
from mathutils import Vector, Matrix
from bmesh.types import BMEdge, BMVert
from ...utils import (
        filter_geom,
        calc_edge_median,
        calc_face_dimensions,
        filter_vertical_edges,
        filter_horizontal_edges
    )


def fill_panel(bm, face, panel_x, panel_y, panel_b, panel_t, panel_d, **kwargs):
    """ Create panels on faace """

    # Create main panel to hold child panels
    bmesh.ops.inset_individual(bm,
        faces=[face], thickness=panel_b)

    # Calculate edges to be subdivided
    n = face.normal
    vedgs = filter_vertical_edges(face.edges, n)
    hedgs = list(set(face.edges) - set(vedgs))

    vts = []
    # Subdivide the edges
    if panel_x:
        res1 = bmesh.ops.subdivide_edges(bm,
            edges=vedgs,
            cuts=panel_x)
        vts = filter_geom(res1['geom_inner'], BMVert)

    if panel_y:
        res2 = bmesh.ops.subdivide_edges(bm,
            edges=hedgs + filter_geom(res1['geom_inner'], BMEdge) if panel_x else hedgs,
            cuts=panel_y)
        vts = filter_geom(res2['geom_inner'], BMVert)

    # Make panels
    if vts:
        faces = list(filter(lambda f: len(f.verts) == 4,
            {f for v in vts for f in v.link_faces if f.normal == n}))

        bmesh.ops.inset_individual(bm, faces=faces, thickness=panel_t / 2)
        bmesh.ops.translate(bm,
            verts=list({v for f in faces for v in f.verts}),
            vec=n * panel_d)

    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

def fill_glass_panes(bm, face, pane_x, pane_y, pane_t, pane_d, **kwargs):
    """ Create glass panes on face """

    v_edges = filter_vertical_edges(face.edges, face.normal)
    h_edges = filter_horizontal_edges(face.edges, face.normal)

    edges = []
    if pane_x:
        res1 = bmesh.ops.subdivide_edges(bm,
            edges=v_edges, cuts=pane_x).get('geom_inner')
        edges.extend(filter_geom(res1, BMEdge))

    if pane_y:
        res2 = bmesh.ops.subdivide_edges(bm,
            edges=h_edges + filter_geom(res1, BMEdge) if pane_x else h_edges,
            cuts=pane_y).get('geom_inner')
        edges.extend(filter_geom(res2, BMEdge))


    if edges:
        pane_faces = list({f for ed in edges for f in ed.link_faces})
        panes = bmesh.ops.inset_individual(bm,
            faces=pane_faces, thickness=pane_t)

        for f in pane_faces:
            bmesh.ops.translate(bm, verts=f.verts, vec=-f.normal * pane_d)

def fill_bar(bm, face, bar_x, bar_y, bar_t, bar_d,**kwargs):

    # Calculate center, width and height of face
    width, height = calc_face_dimensions(face)
    fc = face.calc_center_median()

    # Create Inner Frames
    # -- horizontal
    offset = height / (bar_x + 1)
    for i in range(bar_x):
        # Duplicate
        ret = bmesh.ops.duplicate(bm, geom=[face])
        verts = filter_geom(ret['geom'], BMVert)

        # Scale and translate
        fs =  bar_t / height
        bmesh.ops.scale(bm, verts=verts,
            vec=(1, 1, fs), space=Matrix.Translation(-fc))
        bmesh.ops.translate(bm, verts=verts,
            vec=Vector((face.normal * bar_d / 2)) + Vector((0, 0, -height / 2 + (i + 1) * offset)))

        # Extrude
        ext = bmesh.ops.extrude_edge_only(bm,
            edges=filter_horizontal_edges(filter_geom(ret['geom'], BMEdge), face.normal))
        bmesh.ops.translate(bm,
            verts=filter_geom(ext['geom'], BMVert),
            vec=-face.normal * bar_d / 2)

    # -- vertical
    eps = 0.015
    offset = width / (bar_y + 1)
    for i in range(bar_y):
        # Duplicate
        ret = bmesh.ops.duplicate(bm, geom=[face])
        verts = filter_geom(ret['geom'], BMVert)

        # Scale and Translate
        fs = bar_t / width
        bmesh.ops.scale(bm, verts=verts,
            vec=(fs, fs, 1), space=Matrix.Translation(-fc))
        perp = face.normal.cross(Vector((0, 0, 1)))
        bmesh.ops.translate(bm, verts=verts,
            vec=Vector((face.normal * ((bar_d / 2) - eps))) + perp * (-width / 2 + ((i + 1) * offset)))

        ext = bmesh.ops.extrude_edge_only(bm,
            edges=filter_vertical_edges(filter_geom(ret['geom'], BMEdge), face.normal))
        bmesh.ops.translate(bm,
            verts=filter_geom(ext['geom'], BMVert),
            vec=-face.normal * ((bar_d / 2) - eps))

def fill_louver(bm, face, louver_m, louver_count, louver_d, louver_b, **kwargs):
    normal = face.normal

    # -- inset margin
    if louver_m:
        bmesh.ops.inset_individual(bm,
            faces=[face],
            thickness=louver_m)

    # -- cut vertical edges
    count = (2 * louver_count) - 1
    count = count if count % 2 == 0 else count + 1

    res = bmesh.ops.subdivide_edges(bm,
        edges=filter_vertical_edges(face.edges, face.normal),
        cuts=count)

    # -- find louver faces
    faces = list({f for e in filter_geom(res['geom_inner'], BMEdge)
                    for f in e.link_faces})
    faces.sort(key=lambda f: f.calc_center_median().z)
    louver_faces = faces[1::2]

    # -- scale to border
    for face in louver_faces:
        bmesh.ops.scale(bm,
            vec=(1, 1, 1 + louver_b),
            verts=face.verts,
            space=Matrix.Translation(-face.calc_center_median()))

    # -- extrude louver faces
    res = bmesh.ops.extrude_discrete_faces(bm,
            faces=louver_faces)
    bmesh.ops.translate(bm,
        vec=normal * louver_d,
        verts=list({v for face in res['faces'] for v in face.verts }))

    # -- slope louver faces
    for face in res['faces']:
        top_edge = max(
            filter_horizontal_edges(face.edges, face.normal),
            key= lambda e: calc_edge_median(e).z)

        bmesh.ops.translate(bm,
            vec=-face.normal * louver_d,
            verts=top_edge.verts)

    # -- cleanup
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.01)
'''Maya script to generate realistic parametrized feathers'''

import re
from math import cos, floor, radians, sin, sqrt

import maya.cmds as cmd


########################
########  Lerp  ########
########################
def lerp(a, b, t):
    'Linearly interpolate from a to b by t[0, 1]. Accepts floats or objects with a lerp method.'
    if isinstance(a, float) and isinstance(b, float):
        return (b - a) * t + a
    return a.lerp(b, t)
########################
########  Lerp  ########
########################


########################
###### Line Graph ######
########################


class LineGraph():
    '''Data structure representing a continuous line from 0 to 1 defined by a \
        series of points, with linear interpolation between those points.'''

    def __init__(self, points=None):
        '''points: dict<float[0, 1], *> - Point values indexed by x-axis. \
        If 0 and 1 are not included, they will be inserted with value 0.\
        Values must be valid inputs to the lerp() function.'''

        if not isinstance(points, dict):
            points = {}
        points = {float(key): value for key, value in points.items()}
        if 0.0 not in points:
            points[0.0] = 0.0
        if 1.0 not in points:
            points[1.0] = 0.0
        self.__points = points

    def point_locations(self):
        '''Get the specified x-axis values in sorted order
        returns: float[] - The x-axis values, sorted in ascending order'''
        return sorted(self.__points.keys())

    def to_dict(self):
        'Return the points on this graph as a dictionary'
        return {parameter: value for parameter, value in self.__points.items()}

    def __contains__(self, parameter):
        return parameter in self.__points

    def get(self, parameter):
        'Get the value at parameter, lineraly interpolated if not explicitly defined on the graph'
        parameter = float(parameter)
        if parameter in self.__points:
            return self.__points[parameter]
        parameters = self.point_locations()
        for x in range(1, len(parameters)):
            if parameters[x] >= parameter:
                low = parameters[x - 1]
                high = parameters[x]
                return lerp(self.__points[low], self.__points[high], (parameter - low) / (high - low))
        raise KeyError('Specified parameter was not found in this graph, and the graph was not able to interpolate between defined parameters to determine the value for the provided parameter. Please ensure that the requested parameter is between 0 and 1, inclusive.')

    def __getitem__(self, key):
        'Equivalent to self.get(key)'
        return self.get(key)

    def set(self, parameter, value):
        'Set the value for parameter'
        parameter = float(parameter)
        if 0.0 <= parameter <= 1.0:
            self.__points[parameter] = value
        else:
            raise ValueError('Parameter must be between 0 and 1, inclusive')

    def __setitem__(self, key, value):
        'Equivalent to self.set(key, value)'
        self.set(key, value)

    def lerp(self, other, t):
        '''Linearly interpolate from this graph to another by t
            other: LineGraph - the other LineGraph to interpolate toward
            t: float[0, 1] - How far to interpolate to, 0 being this and 1 being other'''

        result = LineGraph()
        for point in self.point_locations() + other.point_locations():
            result[point] = lerp(self[point], other[point], t)
        return result

    def __str__(self):
        string = '{\n'
        for point in self.point_locations():
            string += '\t{}: {}\n'.format(float(point), str(self[point]))
        return string + '}'
########################
###### Line Graph ######
########################


class BarbParameters():
    'Data structure containing information used in generating barb curves'

    def __init__(self, position, length, start_angle, end_angle):
        '''position: float[0, 1] - The ramp position of these parameters. \
            Barbs will be lerp'd between this and adjacent parameters
        length: float - The length of barbs measured perpendicularly from the rachis
        start_angle: float[0, 180] - The angle (degrees of y-axis rotation) at the base of the barb
        end_angle: float[0, 180] - The angle (degrees of y-axis rotation) at the tip of the barb'''

        # clamp position to [0, 1]
        self.position = sorted([0, float(position), 1])[1]
        self.length = float(length)
        self.start_angle = start_angle
        self.end_angle = end_angle

    def lerp(self, other, t):
        '''Linearly interpolate from this to another parameter set by t
            other: BarbParameters - Parameters to interpolate toward
            t: float[0, 1] - The amount to interpolate, 0 being equivalent to \
                self and 1 being equivalent to other'''

        return BarbParameters(
            lerp(self.position, other.position, t),
            lerp(self.length, other.length, t),
            lerp(self.start_angle, other.start_angle, t),
            lerp(self.end_angle, other.end_angle, t)
        )

    def __str__(self):
        return '''Position: {},\tStart Angle: {},\tEnd Angle: {},\tLength: {}'''.format(self.position, self.start_angle, self.end_angle, self.length)


def make_rachis(length, radius, barb_density, taper=0.0):
    '''Generate a rachis' geometry, ready to have barbs placed on it.
        length: float - The length of the rachis in scene units
        radius: float - The radius of the rachis at the base, in scene units
        barb_density: int - How many barbs the feather will have per scene length unit
        taper: float - The radius of the endpoint and a factor of the starting radius
        returns: str - The name of the generated geometry'''
    curve = cmd.curve(
        p=[
            (0, 0, 0),
            (0, 0, length)
        ],
        degree=1
    )
    cube = cmd.polyCube(
        name='rachis_geo',
        depth=1.0 / barb_density,
        height=float(radius) * 2,
        width=float(radius) * 2,
        subdivisionsX=1,
        subdivisionsY=2,
        subdivisionsZ=1
    )[0]
    cmd.polyExtrudeFacet(
        '{}.f[0:1]'.format(cube),
        divisions=floor(int(barb_density) * length),
        taper=float(taper),
        inputCurve=curve
    )
    cmd.delete(
        cube,
        constraints=True,
        constructionHistory=True,
        inputConnectionsAndNodes=True
    )
    cmd.delete(curve)
    return cube


def make_barb_curves(selection, parameters, mirror):
    '''Generate curves along a series of vertices
        selection: str[] - the vertices to place barbs on, in order from rachis base to tip
        parameters: LineGraph<BarbParameter>
        mirror: bool - Whether to mirror the barbs to the other side of the feather'''

    def draw_barb(position, barb_parameters):
        '''Create an EP curve from position
            position: triple<float> - The cartesian coordinates of the start point
            barb_parameters: BarbParameters - The parameters for the barb'''
        position = tuple(position)
        start_angle = radians(barb_parameters.start_angle)
        end_angle = radians(barb_parameters.end_angle)
        half_length = barb_parameters.length / 2.0
        print('parameter: {}\tstart_angle: {}\tend_angle: {}\tlength: {}'.format(
            barb_parameters.position, start_angle, end_angle, barb_parameters.length))
        points = [(), (), (), ()]
        # start point
        points[0] = position
        # add an additional point because maya seems to require it
        # halfway between the start point and mid point
        points[1] = (
            sin(start_angle) * half_length / 2 + points[0][0],
            0 + points[0][1],
            cos(start_angle) * half_length / 2 + points[0][2]
        )
        # next point makes start_angle from first point to half the barb length
        points[2] = (
            sin(start_angle) * half_length + points[0][0],
            0 + points[0][1],
            cos(start_angle) * half_length + points[0][2]
        )
        # third point makes end_angle from second point to the barb length
        # .01 is to make the angle happen without adding length
        points[3] = (
            sin(end_angle) * half_length + points[2][0],
            0 + points[0][1],
            cos(start_angle) * half_length + points[2][2]
        )
        linear_curve = cmd.curve(
            p=points,
            degree=1,
            k=list(range(len(points)))
        )
        barb = cmd.fitBspline(
            linear_curve,
            name='feather_barb',
            ch=1,
            tol=0.01
        )[0]
        cmd.move(
            position[0],
            position[1],
            position[2],
            '{}.rotatePivot'.format(barb),
            '{}.scalePivot'.format(barb),
            absolute=True,
            worldSpaceDistance=True,
            worldSpace=True
        )
        cmd.delete(
            barb,
            inputConnectionsAndNodes=True,
            constructionHistory=True
        )
        cmd.delete(linear_curve)
        return barb

    count = len(selection)
    barbs = []
    for i in range(count):
        # name of the current vertex
        vertex = selection[i]
        # world position of current selected vertex
        position = cmd.pointPosition(vertex, world=True)
        # normalized position along the selection
        parameter_position = float(i) / max(count - 1, 1)
        # actual parameters for this barb curve
        barb_info = parameters[parameter_position]
        print('parameter_position: {}'.format(parameter_position))
        barbs.append(draw_barb(position, barb_info))
    group = cmd.group(barbs, name='barbs_grp')
    cmd.move(
        0, 0, 0,
        '{}.rotatePivot'.format(group),
        '{}.scalePivot'.format(group),
        absolute=True,
        worldSpaceDistance=True,
        worldSpace=True
    )
    if mirror:
        mirrored_group = cmd.duplicate(group)[0]
        cmd.setAttr('{}.scaleX'.format(mirrored_group), -1)
        return [group, mirrored_group]
    return [group]


def make_feathers(selection, edges, subdivisions, taper):
    '''Duplicates and extrudes a plane's edge(s) along a series of curves
        selection: str[] - The names of the curves to duplicate and extrude onto. \
            The last element will be the source plane to duplicate from
        edges: str - the edges to extrude
        subdivisions: int - the number of divisions in the extrusion
        taper: float - how much thinner the tips should be relative to the bases [0, 1]
        returns: str - The name of the group of newly created feather strands'''

    # the items generated to extrude along each curve
    # selection = sorted(selection[:-1], key=lambda x: float(
    #    cmd.getAttr('{}.translateZ'.format(x))), reverse=True) + [selection[-1]]
    duplicates = []
    for obj in selection[:-1]:
        duplicate = cmd.duplicate(selection[-1])[0]
        old_pivot = cmd.getAttr('{}.rotatePivot'.format(obj))
        cmd.reverseCurve(obj, replaceOriginal=True)
        pos = cmd.pointOnCurve(obj, p=True)  # [x, y, z]
        cmd.move(pos[0], pos[1], pos[2], duplicate, absolute=True)
        edge_or_face = 'edge'
        if edge_or_face == 'edge':
            extrude_edges = [
                '{}.e[{}]'.format(duplicate.encode('UTF-8'), edge)
                for edge in re.split(' +|, *', edges)
            ]
            cmd.polyExtrudeEdge(
                *extrude_edges,
                keepFacesTogether=True,
                divisions=subdivisions,
                twist=0,
                taper=taper,
                offset=0,
                thickness=0,
                inputCurve=obj
            )
        elif edge_or_face == 'face':
            extrude_faces = [
                '{}.f[{}]'.format(duplicate.encode('UTF-8'), face)
                for face in re.split(' +|, *', edges)
            ]
            cmd.polyExtrudeFacet(
                *extrude_faces,
                keepFacesTogether=True,
                divisions=subdivisions,
                twist=0,
                taper=taper,
                offset=0,
                thickness=0,
                inputCurve=obj
            )
            # TODO: end winds up with a double face where the original shape was squashed (2 quad faces sharing the same 4 vertices with opposite normals). Figure out how to fix them
        else:
            raise SyntaxError()

        vertex_count = int(cmd.polyEvaluate(duplicate, vertex=True))
        cmd.scale(
            1, 1e-5, 1,
            *[
                '{}.vtx[{}]'.format(duplicate, i)
                for i in range(0, vertex_count)
            ]
        )
        cmd.polyMergeVertex(duplicate, d=0.05, am=1, ch=1)
        cmd.move(old_pivot[0][0], old_pivot[0][1], old_pivot[0][2], '{}.rotatePivot'.format(
            duplicate), '{}.scalePivot'.format(duplicate), absolute=True, worldSpace=True, worldSpaceDistance=True)
        duplicates.append(duplicate)
    cmd.group(duplicates, name='feather_barbs_geo_grp')
    return duplicates


def dupe_group(selection, group_name='dupe_group_grp'):
    '''Duplicate a group for a selection of vertices so that each duplicated \
            group will be positioned in the same place as its corresponding vertex.
        selection: str - The vertices to duplicate onto, with the last element \
            being the source group to duplicate.
        group_name: str - The name of the group that will contain the newly \
            duplicated and positioned groups.
        returns: str - The actual name of the newly created group (Maya may \
            change group_name if it is invalid)'''

    duplicates = []
    for obj in selection[:-1]:
        duplicate = cmd.duplicate(selection[-1])[0]
        pos = cmd.pointPosition(obj, world=True)
        cmd.move(pos[0], pos[1], pos[2], duplicate, absolute=True,
                 worldSpace=True, rotatePivotRelative=True)
        duplicates.append(duplicate)
    return cmd.group(*duplicates, name=group_name)


def scale_feathers(feathers, scale_factor=1.0, primary_axis='z', secondary_axis='x'):
    '''Scale a selection of feathers
        feathers: str[] - The names of the feathers to scale
        scale_factor: float - How much to increase the size of the feathers, as a factor of the feathers' current sizes. Values[0, 1) decrease feather size.
        primary_axis: {'x', 'y', 'z'} - The primary axis to scale. The feather wil be scaled by a factor of $scaleFactor along this axis. {"x", "y", "z"}
        secondary_axis: {'x', 'y', 'z'} - The secondary axis to scale. This axis will be scaled by the square root of $scaleFactor. {"x", "y", "z"}'''

    for feather in feathers:
        scale = cmd.getAttr('{}.scale'.format(feather))
        primary_axis = primary_axis.lower()
        if primary_axis == 'x':
            scale[0] *= scale_factor
        elif primary_axis == 'y':
            scale[1] *= scale_factor
        elif primary_axis == 'z':
            scale[2] *= scale_factor
        else:
            raise SyntaxError(
                'Invalid axis specified to scale_feathers: ' + primary_axis)

        secondary_axis = secondary_axis.lower()
        scale_factor = sqrt(scale_factor)
        if secondary_axis == 'x':
            scale[0] *= scale_factor
        elif secondary_axis == 'y':
            scale[1] *= scale_factor
        elif secondary_axis == 'z':
            scale[2] *= scale_factor
        else:
            raise SyntaxError(
                'Invalid axis specified to scale_feathers: ' + primary_axis)

        cmd.scale(scale[0], scale[1], scale[2], feather)


def texture_feathers(material):
    '''Apply material to each barb in selection with planar UV mapping
        material: str - The name of the material to apply'''
    cmd.hyperShade(assign=material)
    selection = cmd.ls(sl=True, fl=True)
    for feather in selection:
        try:
            face_count = int(cmd.polyEvaluate(feather, face=True))
            cmd.polyProjection(
                '{}.f[{}:{}]'.format(
                    feather, 0, face_count - 1),
                constructionHistory=True,
                type='Planar',
                insertBeforeDeformers=True,
                mapDirection='y',
                keepImageRatio=True
            )
        except (ValueError, TypeError):
            pass
    # polyProjection -ch 1 -type Planar -ibd on -md y  pPlane123.f[0:31];


def feather_maker_window():
    '''Provide a GUI interface for the above functions'''

    window = cmd.window(title='FeatherMaker')
    cmd.columnLayout(cal='center')

    def generate_rachis(window):
        'temp scope'
        cmd.text(
            al='center',
            fn='boldLabelFont',
            l="Make the feather's rachis"
        )
        cmd.text(
            'Simply input the desired parameters and click generate.',
            al='left'
        )
        length = cmd.floatSliderGrp(
            label='Length',
            f=True,
            min=0.1,
            max=100,
            step=0.1,
            fmn=0.1,
            fmx=10000,
            v=10
        )
        radius = cmd.floatSliderGrp(
            label='Radius',
            f=True,
            min=0.1,
            max=100,
            step=0.1,
            fmn=0.1,
            fmx=10000,
            v=0.5
        )
        barb_density = cmd.intSliderGrp(
            label='Barb Density',
            f=True,
            min=1,
            max=25,
            fmn=1,
            fmx=10000,
            v=10
        )
        taper = cmd.floatSliderGrp(
            label='Taper',
            f=True,
            min=0.0,
            max=1.0,
            step=0.1,
            fmn=0.1,
            fmx=10000,
            v=0.0
        )
        cmd.button(label='Generate rachis', c=lambda *args: make_rachis(
            cmd.floatSliderGrp(length, query=True, v=True),
            cmd.floatSliderGrp(radius, query=True, v=True),
            cmd.intSliderGrp(barb_density, query=True, v=True),
            cmd.floatSliderGrp(taper, query=True, v=True)
        ))
    generate_rachis(window)

    def generate_barb_curves(window):
        'temp scope'
        cmd.text(al='center', fn='boldLabelFont', l="Make feather scaffolding")
        cmd.text(
            'Select the vertices on the rachis, then add to the selection the barb cuve to duplicate.',
            al='left'
        )
        # grp_name = cmd.textField(pht='barb_grp')
        cmd.text(al='center', l='Barb parameters')
        parameters = {}
        positions = {
            'start': 0.1,
            'middle': 0.5,
            'end': 0.95
        }
        cmd.text('Barbs at the base (the very first barb)', al='left')
        parameters['initial'] = {
            'position': 0.0,
            'length': cmd.floatSliderGrp(
                label='Length',
                f=True,
                min=0.1,
                max=10,
                step=0.1,
                fmn=0.1,
                fmx=10000
            ),
            'start_angle': cmd.floatSliderGrp(
                label='Starting angle',
                f=True,
                min=-180,
                max=180,
                step=1
            ),
            'end_angle': cmd.floatSliderGrp(
                label='Ending angle',
                f=True,
                min=-180,
                max=180,
                step=1
            )
        }
        cmd.text('Barbs near the base ({})'.format(
            positions['start']), al='left')
        parameters['start'] = {
            'position': positions['start'],
            'length': cmd.floatSliderGrp(
                label='Length',
                f=True,
                min=0.1,
                max=10,
                step=0.1,
                fmn=0.1,
                fmx=10000
            ),
            'start_angle': cmd.floatSliderGrp(
                label='Starting angle',
                f=True,
                min=-180,
                max=180,
                step=1
            ),
            'end_angle': cmd.floatSliderGrp(
                label='Ending angle',
                f=True,
                min=-180,
                max=180,
                step=1
            )
        }
        cmd.text('Barbs in the middle ({})'.format(
            positions['middle']), al='left')
        parameters['mid'] = {
            'position': positions['middle'],
            'length': cmd.floatSliderGrp(
                label='Length',
                f=True,
                min=0.1,
                max=10,
                step=0.1,
                fmn=0.1,
                fmx=10000
            ),
            'start_angle': cmd.floatSliderGrp(
                label='Starting angle',
                f=True,
                min=-180,
                max=180,
                step=1
            ),
            'end_angle': cmd.floatSliderGrp(
                label='Ending angle',
                f=True,
                min=-180,
                max=180,
                step=1
            )
        }
        cmd.text('Barbs near the tip ({})'.format(positions['end']), al='left')
        parameters['end'] = {
            'position': positions['end'],
            'length': cmd.floatSliderGrp(
                label='Length',
                f=True,
                min=0.1,
                max=10,
                step=0.1,
                fmn=0.1,
                fmx=10000
            ),
            'start_angle': cmd.floatSliderGrp(
                label='Starting angle',
                f=True,
                min=-180,
                max=180,
                step=1
            ),
            'end_angle': cmd.floatSliderGrp(
                label='Ending angle',
                f=True,
                min=-180,
                max=180,
                step=1
            )
        }
        mirror = cmd.checkBox(label='Mirror barbs', value=True)

        cmd.button(
            label='Make barbs',
            command=lambda *args: make_barb_curves(
                cmd.ls(sl=True, fl=True),
                LineGraph({
                    0.0: BarbParameters(
                        parameters['initial']['position'],
                        cmd.floatSliderGrp(
                            parameters['initial']['length'],
                            query=True,
                            v=True
                        ),
                        cmd.floatSliderGrp(
                            parameters['initial']['start_angle'],
                            query=True,
                            v=True
                        ) + 5.0,
                        cmd.floatSliderGrp(
                            parameters['initial']['end_angle'],
                            query=True,
                            v=True
                        )
                    ),
                    parameters['start']['position']: BarbParameters(
                        parameters['start']['position'],
                        cmd.floatSliderGrp(
                            parameters['start']['length'],
                            query=True,
                            v=True
                        ),
                        cmd.floatSliderGrp(
                            parameters['start']['start_angle'],
                            query=True,
                            v=True
                        ),
                        cmd.floatSliderGrp(
                            parameters['start']['end_angle'],
                            query=True,
                            v=True
                        )
                    ),
                    parameters['mid']['position']: BarbParameters(
                        parameters['mid']['position'],
                        cmd.floatSliderGrp(
                            parameters['mid']['length'],
                            query=True,
                            v=True
                        ),
                        cmd.floatSliderGrp(
                            parameters['mid']['start_angle'],
                            query=True,
                            v=True
                        ),
                        cmd.floatSliderGrp(
                            parameters['mid']['end_angle'],
                            query=True,
                            v=True
                        )
                    ),
                    parameters['end']['position']: BarbParameters(
                        parameters['end']['position'],
                        cmd.floatSliderGrp(
                            parameters['end']['length'],
                            query=True,
                            v=True
                        ),
                        cmd.floatSliderGrp(
                            parameters['end']['start_angle'],
                            query=True,
                            v=True
                        ),
                        cmd.floatSliderGrp(
                            parameters['end']['end_angle'],
                            query=True,
                            v=True
                        )
                    ),
                    1.0: BarbParameters(
                        1.0,
                        0.0,
                        cmd.floatSliderGrp(
                            parameters['end']['start_angle'],
                            query=True,
                            v=True
                        ),
                        cmd.floatSliderGrp(
                            parameters['end']['end_angle'],
                            query=True,
                            v=True
                        )
                    )
                }),
                cmd.checkBox(mirror, query=True, value=True)
            )
        )
    generate_barb_curves(window)

    def generate_barb_polies(window):
        'temp scope'
        cmd.text(al='center', fn='boldLabelFont', l='Fill out feather barbs')
        cmd.text(
            'Select your curves that represent the feather barbs, then add to the selection your source plane.',
            al='left'
        )
        cmd.text(label='Edge(s):')
        edge = cmd.textField(pht='0, 2')
        divisions = cmd.intSliderGrp(
            f=True, label='Subdivisions', min=0, max=30, fmn=0, fmx=1000000, v=10)
        taper = cmd.floatSliderGrp(
            f=True, label='Taper', min=0, max=4, fmn=0, fmx=1000000, v=1)
        cmd.button(
            label='Fill feather',
            c=lambda *args: make_feathers(
                cmd.ls(sl=True, fl=True),
                cmd.textField(edge, query=True, text=True),
                cmd.intSliderGrp(divisions, query=True, v=True),
                cmd.floatSliderGrp(taper, query=True, v=True)
            )
        )
    generate_barb_polies(window)

    def texture_barbs(window):
        'temp scope'
        cmd.text(al='center', fn='boldLabelFont', l='Texture barbs')
        cmd.text(
            'Select your barbs, then enter the material to apply to them below.',
            al='left'
        )
        material = cmd.textField(pht='lambert1')
        cmd.button(
            label='Texture barbs',
            c=lambda *args: texture_feathers(
                # cmd.ls(sl=True, fl=True),
                cmd.textField(material, query=True, text=True)
            )
        )
    texture_barbs(window)

    def place_feathers(window):
        'temp scope'
        cmd.text(al='center', fn='boldLabelFont', l='Place feathers')
        cmd.text(
            al='left',
            l='Select the vertices where you want feathers to be placed, then add to your selection the feather object.'
        )
        cmd.text(al='left', l='Output group name:')
        grp_name = cmd.textField(pht='feathers_grp')
        cmd.button(
            label='Place feathers',
            c=lambda *args: dupe_group(
                cmd.ls(sl=True, fl=True),
                cmd.textField(grp_name, query=True, tx=True)
            )
        )
    place_feathers(window)

    def perform_feather_scale(window):
        'temp scope'
        cmd.text(al='center', fn='boldLabelFont', l='Scale feathers')
        scale_slider = cmd.floatSliderGrp(
            f=True, label='Scale', min=0, max=4, s=0.1, pre=1, v=1.0)
        scale_main_axis = cmd.optionMenu(label='Main Axis: ')
        cmd.menuItem(label='x')
        cmd.menuItem(label='y')
        cmd.menuItem(label='z')
        scale_secondary_axis = cmd.optionMenu(label='Secondary Axis: ')
        cmd.menuItem(label='z')
        cmd.menuItem(label='y')
        cmd.menuItem(label='x')
        cmd.button(
            label='Scale feathers',
            c=lambda *args: scale_feathers(
                cmd.ls(sl=True, fl=True),
                cmd.floatSliderGrp(scale_slider, query=True, v=True),
                cmd.optionMenu(scale_main_axis, query=True, v=True),
                cmd.optionMenu(scale_secondary_axis, query=True, v=True),
            )
        )
    perform_feather_scale(window)

    cmd.text(al='left', l='Developed by the AVC @ USF, 2018')

    # Now display the window
    cmd.showWindow(window)


feather_maker_window()

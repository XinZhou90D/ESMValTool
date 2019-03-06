"""
Area operations on data cubes.

Allows for selecting data subsets using certain latitude and longitude bounds;
selecting geographical regions; constructing area averages; etc.
"""
import logging

import iris
import numpy as np


logger = logging.getLogger(__name__)


# guess bounds tool
def _guess_bounds(cube, coords):
    """Guess bounds of a cube, or not."""
    # check for bounds just in case
    for coord in coords:
        if not cube.coord(coord).has_bounds():
            cube.coord(coord).guess_bounds()
    return cube


# slice cube over a restricted area (box)
def extract_region(cube, start_longitude, end_longitude, start_latitude,
                   end_latitude):
    """
    Extract a region from a cube.

    Function that subsets a cube on a box (start_longitude, end_longitude,
    start_latitude, end_latitude)
    This function is a restriction of masked_cube_lonlat();

    Arguments
    ---------
        cube: iris.cube.Cube
            input cube.

        start_longitude: float
            Western boundary longitude.

        end_longitude: float
              Eastern boundary longitude.

        start_latitude: float
             Southern Boundary latitude.

        end_latitude: float
             Northern Boundary Latitude.

    Returns
    -------
    iris.cube.Cube
        smaller cube.
    """
    # Converts Negative longitudes to 0 -> 360. standard
    start_longitude = float(start_longitude)
    end_longitude = float(end_longitude)
    start_latitude = float(start_latitude)
    end_latitude = float(end_latitude)

    if cube.coord('latitude').ndim == 1:
        region_subset = cube.intersection(
            longitude=(start_longitude, end_longitude),
            latitude=(start_latitude, end_latitude))
        region_subset = region_subset.intersection(longitude=(0., 360.))
        return region_subset
    # irregular grids
    lats = cube.coord('latitude').points
    lons = cube.coord('longitude').points
    mask = np.ma.array(cube.data).mask
    mask += np.ma.masked_where(lats < start_latitude, lats).mask
    mask += np.ma.masked_where(lats > end_latitude, lats).mask
    mask += np.ma.masked_where(lons > start_longitude, lons).mask
    mask += np.ma.masked_where(lons > end_longitude, lons).mask
    cube.data = np.ma.masked_where(mask, cube.data)
    return cube


def get_iris_analysis_operation(operator):
    """
    Determine the iris analysis operator from a string.

    Arguments
    ---------
        operator: string
            A named operator.
    Returns
    -------
        function: A function from iris.analysis
    """
    operators = ['mean', 'median', 'stdev', 'variance', 'min', 'minimum',
                 'max', 'maximum']
    operator = operator.lower()
    if operator == 'mean':
        operation = iris.analysis.MEAN
    elif operator == 'median':
        operation = iris.analysis.MEDIAN
    elif operator == 'stdev':
        operation = iris.analysis.STD_DEV
    elif operator == 'variance':
        operation = iris.analysis.VARIANCE
    elif operator in ['minimum', 'min']:
        operation = iris.analysis.MIN
    elif operator in ['maximum', 'max']:
        operation = iris.analysis.MAX
    else:
        raise ValueError('operator ({}) not recognised. Accepted values are: '
                         '{}', operator, operators)
    return operation


def zonal_means(cube, coordinate, mean_type):
    """
    Get zonal means.

    Function that returns zonal means along a coordinate `coordinate`;
    the type of mean is controlled by mean_type variable (string)::

        'mean' -> MEAN
        'median' -> MEDIAN
        'stdev' -> STD_DEV
        'variance' -> VARIANCE
        'min' -> MIN
        'max' -> MAX

    Arguments
    ---------
        cube: iris.cube.Cube
            input cube.

         coordinate: str
             name of coordinate to make mean

         mean_type: str
             Type of analysis to use, from iris.analysis.

    Returns
    -------
    iris.cube.Cube
        Returns a cube
    """
    operation = get_iris_analysis_operation(mean_type)
    return cube.collapsed(coordinate, operation)


# get the area average
def average_region(cube, coord1, coord2, operator='mean', fx_files=None):
    """
    Determine the area average.

    Can be used with coord1 and coord2 (strings,
    usually 'longitude' and 'latitude' but depends on the cube);

    Arguments
    ---------
        cube: iris.cube.Cube
            input cube.
        coord1: str
            Name of the firct coordinate dimension
        coord2: str
            Name of the second coordinate dimension
        operator: str
            Name of the operation to apply (default: mean)
        fx_files: dictionary
            dictionary of field:filename for the fx_files

    Returns
    -------
    iris.cube.Cube
        collapsed cube.
    """
    grid_areas_found = False
    grid_areas = None
    if fx_files:
        for key, fx_file in fx_files.items():
            if fx_file is None:
                continue
            logger.info('Attempting to load %s from file: %s', key, fx_file)
            fx_cube = iris.load_cube(fx_file)

            grid_areas = fx_cube.data
            grid_areas_found = True
            cube_shape = cube.data.shape
            if cube.data.ndim == 4 and grid_areas.ndim == 2:
                grid_areas = np.tile(grid_areas,
                                     [cube_shape[0], cube_shape[1], 1, 1])
            elif cube.data.ndim == 4 and grid_areas.ndim == 3:
                grid_areas = np.tile(grid_areas,
                                     [cube_shape[0], 1, 1, 1])
            elif cube.data.ndim == 3 and grid_areas.ndim == 2:
                grid_areas = np.tile(grid_areas,
                                     [cube_shape[0], 1, 1])

    if not fx_files and cube.coord('latitude').points.ndim == 2:
        logger.error('average_region ERROR: fx_file needed to calculate grid'
                     + ' cell area for irregular grids.')
        raise iris.exceptions.CoordinateMultiDimError(cube.coord('latitude'))

    if not grid_areas_found:
        cube = _guess_bounds(cube, [coord1, coord2])
        grid_areas = iris.analysis.cartography.area_weights(cube)
        logger.info('Calculated grid area:{}'.format(grid_areas.shape))

    if cube.data.shape != grid_areas.shape:
        raise ValueError('Cube shape ({}) doesn`t match grid area shape '
                         '({})'.format(cube.data.shape, grid_areas.shape))

    operation = get_iris_analysis_operation(operator)

    # TODO: implement weighted stdev, median, and var when available in iris.
    # See iris issue: https://github.com/SciTools/iris/issues/3208

    if operator in ['mean', ]:
        return cube.collapsed([coord1, coord2],
                              operation,
                              weights=grid_areas)

    # Many IRIS analysis functions do not accept weights arguments.
    return cube.collapsed([coord1, coord2], operation)


def extract_named_regions(cube, regions):
    """
    Extract a specific named region.

    The region coordinate exist in certain CMIP datasets.
    This preprocessor allows a specific named regions to be extracted.

    Arguments
    ---------
    cube: iris.cube.Cube
       input cube.

    regions: str, list
        A region or list of regions to extract.

    Returns
    -------
    iris.cube.Cube
        collapsed cube.
    """
    # Make sure regions is a list of strings
    if isinstance(regions, str):
        regions = [regions, ]

    if not isinstance(regions, (list, tuple, set)):
        raise ValueError('Regions "{}" is not an acceptable format.'
                         ''.format(regions))

    available_regions = set(cube.coord('region').points)
    invalid_regions = set(regions) - available_regions
    if invalid_regions:
        raise ValueError('Region(s) "{}" not in cube region(s): '
                         '{}'.format(invalid_regions, available_regions))

    constraints = iris.Constraint(region=lambda r: r in regions)
    cube = cube.extract(constraint=constraints)
    return cube

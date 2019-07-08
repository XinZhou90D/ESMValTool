# =====================================
# generalised_extreme_value_analysis.py
# =====================================
#
# Apply GEV analysis to daily precipitation output by PRIMAVERA
# Stream 1 model simulations, grid point-by-grid point (WP1).
# Additional script available to aggregate GEV results over
# large river basins within Europe (WP10).
#
# Notes:
#   * Parametric 1-day block maxima method applied seasonally.
#   * GEV analysis run within R interface ('extRemes').
#   * EC-Earth model grid coords are transformed herein.
#   * CNRM-CERFACS model is transformed to regular grid and
#     transformed data are output herein.
#   * CMCC model data are preprocessed from 6-hourly output
#     using 'preprocess_cmcc_day_pr.py'.
#
# Alexander J. Baker, UREAD
# 19/10/2017
# alexander.baker@reading.ac.uk
#############################################################


import os
import logging

import numpy as np
import iris
import iris.cube
import iris.analysis
import iris.util
import rpy2.robjects

import esmvaltool.diag_scripts.shared
from esmvaltool.diag_scripts.shared.plot import quickplot
import esmvaltool.diag_scripts.shared.names as n

logger = logging.getLogger(os.path.basename(__file__))


class ExtremePrecipitation(object):

    def __init__(self, config):
        self.cfg = config
        self.filenames = esmvaltool.diag_scripts.shared.Datasets(self.cfg)
        self.return_period = self.cfg['return_period']
        self.confidence_interval = self.cfg['confidence_interval']

        self.gev_param_symbols = ['mu', 'sigma', 'xi']
        self.gev_param_name = dict(mu='location', sigma='scale', xi='shape')
        self.return_period = rpy2.robjects.IntVector(self.return_period)

    def _get_return_period_name(self, period):
        return '{}-year level'.format(self.return_period[r])

    def compute(self):
        from rpy2.robjects import r as R, numpy2ri
        from rpy2.robjects.packages import importr

        extRemes = importr('extRemes')
        numpy2ri.activate()
        R['options'](warn=-1)
        for filename in self.filenames:
            logger.info('Processing %s', filename)
            cube = iris.load_cube(filename)
            logger.info(cube)

            model_cube = cube[0, ...]
            shape = model_cube.shape
            units = model_cube.units

            for season in set(cube.coords('clim_season')):
                # Clean R objects
                R('rm(list = ls())')
                logger.info('Processing season %s', season)
                season_cube = cube.extract(iris.Constraint(clim_season=season))

                logger.info('GEV analysis...')
                fevd = dict()
                for par in self.gev_param_symbols:
                    fevd[par] = np.full(shape, np.nan)

                rl = dict()
                for period in self.return_period:
                    rl[period] = np.full(shape, np.nan)

                for x in range(shape[0]):
                    for y in range(shape[1]):
                        data = cube.data[..., x, y]
                        if np.any(data):
                            self._compute_metric(
                                data, units, fevd, rl, extRemes, x, y
                            )

                for par, data in fevd.items():
                    fevd[par] = self._create_cube(data, par, model_cube)

                for period, data in rl.items():
                    rl[period] = self._create_cube(
                        data,
                        self._get_return_period_name(period),
                        model_cube
                    )
                self._plot_results(filename, season, fevd, rl)
                self._save_results(filename, season, fevd, rl)


    def _compute_metric(self, data, units, fevd, rl, extRemes, x, y):
        evdf = extRemes.fevd(data, units=units.origin)
        results = evdf.rx2('results').rx2('par')
        # -ve mu/sigma invalid
        if results.rx2('location')[0] > 0. and results.rx2('scale')[0] > 0.:
            for par in self.gev_param_symbols:
                fevd[par][x, y] = results.rx2(self.gev_param_name[par])[0]
            r_level = extRemes.return_level(
                evdf,
                return_period=self.return_period,
                qcov=extRemes.make_qcov(evdf)
            )
            for data, period in zip(r_level, self.return_period):
                rl[period][x, y] = data

    def _create_cube(self, data, name, model_cube):
        cube = model_cube.copy(data)
        cube.standard_name = None
        cube.long_name = name
        cube.var_name = None
        return cube

    def _plot_results(self, filename, season, fevd, rl):
        if not self.cfg[n.WRITE_PLOTS]:
            return
        logger.info('Plot results')
        results_subdir = os.path.join(
            self.filenames.get_info(n.PLOT_DIR, filename),
            self.filenames.get_info(n.PROJECT, filename),
            self.filenames.get_info(n.DATASET, filename),
            season,
        )
        for par in self.gev_param_symbols:
            par_ffp = os.path.join(
                results_subdir,
                '{}.{}'.format(
                    self.gev_param_name[par],
                    self.cfg[n.OUTPUT_FILE_TYPE]
                )
            )
            quickplot(
                fevd[par],
                filename=par_ffp,
                **(self.cfg.get('gev_quickplot', {}))
            )
        for return_period in rl:
            return_periods_path = os.path.join(
                results_subdir,
                'return_period_{}years.{}'.format(
                    return_period,
                    self.cfg[n.OUTPUT_FILE_TYPE]
                )
            )
            quickplot(
                rl[return_period],
                filename=return_periods_path,
                **(self.cfg.get('return_period_quickplot', {}))
            )

    def _save_results(self, filename, season, fevd, rl):
        if not self.cfg[n.WRITE_NETCDF]:
            return
        logger.info('Saving data...')
        results_subdir = os.path.join(
            self.filenames.get_info(n.WORK_DIR, filename),
            self.filenames.get_info(n.PROJECT, filename),
            self.filenames.get_info(n.DATASET, filename),
            season,
        )
        for par in self.gev_param_symbols:
            par_ffp = os.path.join(results_subdir, '{}.nc'.format(par))
            iris.save(fevd[par], par_ffp)

        return_periods_path = os.path.join(
            results_subdir, 'return_periods.nc'
        )
        iris.save(rl.values(), return_periods_path)


def main():
    with esmvaltool.diag_scripts.shared.run_diagnostic() as config:
        ExtremePrecipitation(config).compute()


if __name__ == "__main__":
    main()

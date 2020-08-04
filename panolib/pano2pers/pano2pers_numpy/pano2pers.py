#!/usr/bin/env python3

from typing import Dict, List, Tuple, Union

import numpy as np

from panolib.grid_sample import numpy_func

from .utils import create_rotation_matrix
from ..base import BasePano2Pers

__all__ = ["Pano2Pers"]


class Pano2Pers(BasePano2Pers):

    def __init__(self, **kwargs):
        r"""Pano2Pers Numpy
        """
        super().__init__(**kwargs)

        # initialize intrinsic matrix
        _ = self.intrinsic_matrix
        # initialize global to camera rotation matrix
        _ = self.global2camera_rotation_matrix

    @property
    def intrinsic_matrix(self) -> np.ndarray:
        r"""Create Intrinsic Matrix

        return:
            K: 3x3 matrix numpy.ndarray

        NOTE:
            ref: http://ksimek.github.io/2013/08/13/intrinsic/
        """
        if not hasattr(self, '_K'):
            # perspective projection (focal length)
            f = self.w_pers / (2. * np.tan(np.radians(self.fov_x) / 2.))
            # transform between camera frame and pixel coordinates
            self._K = np.array([
                [f, self.skew, self.w_pers/2],
                [0., f, self.h_pers/2],
                [0., 0., 1.]])
        return self._K

    @property
    def perspective_coordinate(self) -> np.ndarray:
        r"""Create mesh coordinate grid with perspective height and width

        return:
            coordinate: numpy.ndarray
        """
        _xs = np.linspace(0, self.w_pers-1, self.w_pers)
        _ys = np.linspace(0, self.h_pers-1, self.h_pers)
        xs, ys = np.meshgrid(_xs, _ys)
        zs = np.ones_like(xs)
        coord = np.stack((xs, ys, zs), axis=2)
        return coord

    @property
    def global2camera_rotation_matrix(self) -> np.ndarray:
        r"""Default rotation that changes global to camera coordinates
        """
        if not hasattr(self, '_g2c_rot'):
            x = np.pi
            y = np.pi
            z = np.pi
            self._g2c_rot = create_rotation_matrix(x=x, y=y, z=z)
        return self._g2c_rot

    def rotation_matrix(
        self,
        roll: float,
        pitch: float,
        yaw: float,
    ) -> np.ndarray:
        r"""Create Rotation Matrix

        params:
            roll: x-axis rotation float
            pitch: y-axis rotation float
            yaw: z-axis rotation float

        return:
            rotation matrix: numpy.ndarray

        Camera coordinates -> z-axis points forward, y-axis points upward
        Global coordinates -> x-axis points forward, z-axis poitns upward
        """
        R_g2c = self.global2camera_rotation_matrix
        R = create_rotation_matrix(x=roll, y=pitch, z=yaw)
        R = R_g2c @ R
        return R

    @staticmethod
    def _get_img_size(img: np.ndarray) -> Tuple[int]:
        r"""Return height and width"""
        return img.shape[-2:]

    def _run_single(
        self,
        pano: np.ndarray,
        rot: Dict[str, float],
        sampling_method: str,
        mode: str,
    ) -> np.ndarray:
        # define variables
        h_pano, w_pano = self._get_img_size(pano)
        m = self.perspective_coordinate
        K = self.intrinsic_matrix
        R = self.rotation_matrix(**rot)

        # conversion:
        # m = P @ M
        # P = K @ [R | t] = K @ R (in this case)
        # M = R^-1 @ K^-1 @ m
        K_inv = np.linalg.inv(K)
        R_inv = np.linalg.inv(R)
        m = m[:, :, :, np.newaxis]
        M = R_inv @ K_inv @ m
        M = M.squeeze(3)

        # calculate rotations per perspective coordinates
        phi = np.arcsin(M[:, :, 1] / np.linalg.norm(M, axis=-1))
        theta = np.arctan2(M[:, :, 0], M[:, :, 2])

        # center the image and convert to pixel location
        ui = (theta - np.pi) * w_pano / (2 * np.pi)
        uj = (phi - np.pi / 2) * h_pano / np.pi
        # out-of-bounds calculations
        ui = np.where(ui < 0, ui + w_pano, ui)
        ui = np.where(ui >= w_pano, ui - w_pano, ui)
        uj = np.where(uj < 0, uj + h_pano, uj)
        uj = np.where(uj >= h_pano, uj - h_pano, uj)
        grid = np.stack((uj, ui), axis=0)

        # grid sample
        grid_sample = getattr(
            numpy_func,
            sampling_method,
            "faster"
        )
        sampled = grid_sample(pano, grid, mode=mode)
        return sampled

    def __call__(
        self,
        pano: Union[np.ndarray, List[np.ndarray]],
        rot: Union[Dict[str, float], List[Dict[str, float]]],
        sampling_method: str = "faster",
        mode: str = "bilinear",
    ) -> np.ndarray:
        r"""Run Pano2Pers

        params:
            pano: panorama image np.ndarray[C, H, W]
            rot: Dict[str, float]
            sampling_method: str (default="faster")
            mode: str (default="bilinear")

        returns:
            pers: perspective image np.ndarray[C, H, W]

        NOTE: input can be batched [B, C, H, W] or List[np.ndarray]
        NOTE: when using batches, the output types match
        """
        _return_type = type(pano)
        _original_shape_len = len(pano.shape)
        if _return_type == np.ndarray:
            assert _original_shape_len >= 3, \
                f"ERR: got {_original_shape_len} for input pano"
            if _original_shape_len == 3:
                pano = pano[np.newaxis, :, :, :]
                rot = [rot]

        assert len(pano) == len(rot), \
            f"ERR: length of pano and rot differs {len(pano)} vs {len(rot)}"

        samples = []
        for p, r in zip(pano, rot):
            # iterate through batches
            # TODO: batch implementation
            sample = self._run_single(
                pano=p,
                rot=r,
                sampling_method=sampling_method,
                mode=mode,
            )
            samples.append(
                sample
            )

        if _return_type == np.ndarray:
            samples = np.stack(samples, axis=0)
            if _original_shape_len == 3:
                samples = np.squeeze(samples, axis=0)

        return samples
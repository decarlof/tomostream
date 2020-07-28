import numpy as np
import cupy as cp
from cupyx.scipy.fft import rfft, irfft
from cupyx.scipy.fftpack import get_fft_plan
from .kernels import orthox, orthoy, orthoz


class Solver():
    """Class for tomography reconstruction of orthogonal slices through direct 
    discreatization of line integrals in the Radon transform.
    Attributes
    ----------
    ntheta : int
        The number of projections in the buffer (for simultaneous reconstruction)
    n, nz : int
        The pixel width and height of the projection.
    """

    def __init__(self, ntheta, n, nz):
        self.n = n
        self.nz = nz
        self.ntheta = ntheta
        self.nthetapart = 64 # number of projections for simultatneous processing by a GPU

    def setFlat(self, data):
        self.flat = cp.array(np.mean(data, axis=0)).reshape(self.nz, self.n)

    def setDark(self, data):
        self.dark = cp.array(np.mean(data, axis=0)).reshape(self.nz, self.n)

    def backProjection(self, data, theta, center, idx, idy, idz):
        obj = cp.zeros([self.n, 3*self.n], dtype='float32')
        obj[:self.nz, :self.n] = orthox(data, theta, center, idx)
        obj[:self.nz, self.n:2*self.n] = orthoy(data, theta, center, idy)
        obj[:self.n, 2*self.n:3*self.n] = orthoz(data, theta, center, idz)
        return obj

    def fbpFilter(self, data):
        freq = cp.fft.rfftfreq(self.n)
        wfilter = freq * 4 * (1 - freq * 2)**3
        for k in range(data.shape[0]):
            data[k] = irfft(wfilter*rfft(data[k], overwrite_x=True,
                                         axis=1), overwrite_x=True, axis=1)
        return data

    def stripeRemovalFilter(self, data):
        # to implement
        return data

    def darkFlatFieldCorrection(self, data):
        data = (data-self.dark)/cp.maximum(self.flat-self.dark, 1e-6)
        return data

    def minusLog(self, data):
        data = -cp.log(cp.maximum(data, 1e-6))
        return data

    def reconPart(self, data, theta, center, idx, idy, idz):
        data = self.darkFlatFieldCorrection(data)
        data = self.minusLog(data)
        data = self.stripeRemovalFilter(data)
        data = self.fbpFilter(data)
        rec = self.backProjection(data, theta, center, idx, idy, idz)
        return rec

    def recon(self, data, theta, center, idx, idy, idz):
        for k in range(int(np.ceil(self.ntheta/self.nthetapart))):
            ids = np.arange(k*self.nthetapart,
                            min((k+1)*self.nthetapart, self.ntheta))
            datagpu = cp.array(data[ids]).reshape(len(ids), self.nz, self.n)
            thetagpu = cp.array(theta[ids])*np.pi/180
            if(k == 0):
                recgpu = self.reconPart(
                    datagpu, thetagpu, center, idx, idy, idz)
            else:
                recgpu += self.reconPart(datagpu,
                                         thetagpu, center, idx, idy, idz)
        return recgpu.get()
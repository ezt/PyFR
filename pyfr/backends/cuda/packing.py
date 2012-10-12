# -*- coding: utf-8 -*-

import pycuda.driver as cuda
from pycuda.compiler import SourceModule

from pyfr.backends.cuda.provider import CudaKernelProvider
from pyfr.backends.cuda.queue import CudaComputeKernel, CudaMPIKernel

from pyfr.util import npdtype_to_ctype, npdtype_to_mpitype

class CudaPackingKernels(CudaKernelProvider):
    def __init__(self, backend):
        pass

    def _tplopts(self, view):
        return dict(view_order=view.order,
                    mat_ctype=npdtype_to_ctype(view.viewof.dtype))

    def _packunpack(self, op, view):
        # Get the CUDA pack/unpack kernel from the pack module
        fn = self._get_function('pack', op, 'PPiiiP', self._tplopts(view))

        # Compute the grid and thread-block size
        grid, block = self._get_2d_grid_block(fn, view.nrow, view.ncol)

        class PackUnpackKernel(CudaComputeKernel):
            def __call__(self, stream):
                # If we are unpacking then copy the buffer to the GPU
                if op == 'unpack':
                    cuda.memcpy_htod_async(view.gbuf, view.hbuf, stream)

                # Call the CUDA kernel (pack or unpack)
                fn.prepared_async_call(grid, block, stream, view.viewof.data,
                                       view.data, view.nrow, view.ncol,
                                       view.leaddim, view.gbuf)

                # If we have been packing then copy the buffer to the host
                if op == 'pack':
                    cuda.memcpy_dtoh_async(view.hbuf, view.gbuf, stream)

        return PackUnpackKernel()

    def _sendrecv(self, view, mpipreqfn, pid, tag):
        # Determine the MPI data type the view packs to/unpacks from
        mpitype = npdtype_to_mpitype(view.viewof.dtype)

        # Create a persistent MPI request to send/recv the pack
        preq = mpipreqfn((view.hbuf, mpitype), pid, tag)

        class SendRecvPackKernel(CudaMPIKernel):
            def __call__(self, reqlist):
                # Start the request and append us to the list of requests
                preq.Start()
                reqlist.append(preq)

        return SendRecvPackKernel()

    def pack(self, view):
        return self._packunpack('pack', view)

    def send_pack(self, view, mpicomm, pid, tag):
        return self._sendrecv(view, mpicomm.Send_init, pid, tag)

    def recv_pack(self, view, mpicomm, pid, tag):
        return self._sendrecv(view, mpicomm.Recv_init, pid, tag)

    def unpack(self, view):
        return self._packunpack('unpack', view)
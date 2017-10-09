'''
Utility class to handle BlockMatrix made from scipy-sparse and
Hypre with the same interface
'''
import numpy as np
import scipy
from scipy.sparse import coo_matrix, spmatrix, lil_matrix

from petram.mfem_config import use_parallel
import mfem.common.chypre as chypre

if use_parallel:
   from petram.helper.mpi_recipes import *
   from mfem.common.parcsr_extra import *
   import mfem.par as mfem
   default_kind = 'hypre'
else:
   import mfem.ser as mfem
   default_kind = 'scipy'

from petram.solver.solver_utils import make_numpy_coo_matrix
from petram.helper.matrix_file import write_coo_matrix, write_vector

import petram.debug as debug
dprint1, dprint2, dprint3 = debug.init_dprints('BlockMatrix')
format_memory_usage = debug.format_memory_usage

class One(object):
    '''
    An identity matrix (used in P and mimic 1*X = X)
    '''
    def __init__(self, ref):
        self._shape = ref.shape
        self._is_hypre = False
        if hasattr(ref, "GetColPartArray"):
           self._cpart = ref.GetColPartArray()
           self._is_hypre = True
        if hasattr(ref, "GetRowPartArray"):
           self._rpart = ref.GetRowPartArray()
           self._is_hypre = True

    def __repr__(self):
        return "IdentityMatrix"
    @property
    def shape(self): return self._shape

    @property
    def nnz(self):
        return self.shape[0]

    def true_nnz(self):
        return self.shape[0]

    def GetColPartArray(self):
        return self._cpart
     
    def GetRowPartArray(self):
        return self._rpart
     
    def __mul__(self, other):
        return other
    def transpose(self):
        return self
    def dot(self, other):
        return other
    @property
    def isHypre(self):
        return self._is_hypre
     
class ScipyCoo(coo_matrix):
    def true_nnz(self):
        if hasattr(self, "eliminate_zeros"):
            self.eliminate_zeros()
        return self.nnz
   
    def __add__(self, other):
        ret = super(ScipyCoo, self).__add__(other)
        return convert_to_ScipyCoo(ret)
     
    def __sub__(self, other):
        ret = super(ScipyCoo, self).__sub__(other)
        return convert_to_ScipyCoo(ret)
     
    def setDiag(self, idx, value=1.0):
        ret = self.tolil()
        for i in idx:
           ret[i,i] = value
        ret = ret.tocoo()
        self.data = ret.data
        self.row  = ret.row
        self.col  = ret.col
        
    def resetDiagImag(self, idx):
        ret = self.tolil()
        for i in idx:
           ret[i,i] = ret[i,i].real
        ret = ret.tocoo()
        self.data = ret.data
        self.row  = ret.row
        self.col  = ret.col
        

    def resetRow(self, rows):
        ret = self.tolil()
        for r in rows: ret[r, :] = 0.0        
        ret = ret.tocoo()
        self.data = ret.data
        self.row  = ret.row
        self.col  = ret.col
       
    def resetCol(self, cols):
        ret = self.tolil()
        for c in cols: ret[:, c] = 0.0        
        ret = ret.tocoo()
        self.data = ret.data
        self.row  = ret.row
        self.col  = ret.col
     
    def selectRows(self, nonzeros):
        m = self.tocsr()
        ret = (m[nonzeros,:]).tocoo()
        return convert_to_ScipyCoo(ret)
     
    def selectCols(self, nonzeros):
        m = self.tocsc()
        ret = (m[:, nonzeros]).tocoo()
        return convert_to_ScipyCoo(ret)        
     
    def rap(self, P):
        PP = P.conj().transpose()
        return convert_to_ScipyCoo(PP.dot(self.dot(P)))

    def elimination_matrix(self, nonzeros):
        '''
        # P elimination matrix for column vector
        [1 0  0][x1]    [x1]
        [0 0  1][x2]  = [x3]
                [x3]    

        P^t (transpose does reverse operation)
           [1 0][x1]    [x1]
           [0 0][x3]  = [0]
           [0,1]        [x3]

        # P^t does elimination matrix for horizontal vector
                  [1,0]    
        [x1 x2 x3][0,0]  = [x1, x3]
                  [0,1]

        # P does reverse operation for horizontal vector
               [1,0 0]    
        [x1 x3][0,0 1]  = [x1, 0  x3]
        '''
        ret = lil_matrix((len(nonzeros), self.shape[0]))
        for k, z in enumerate(nonzeros):
            ret[k, z] = 1.
        return convert_to_ScipyCoo(ret.tocoo())
     
    def get_global_coo(self):
        '''
        global representation:
           zero on non-root node
        '''
        try:
           from mpi4py import MPI
           myid = MPI.COMM_WORLD.rank
           if myid != 0:
              return coo_matrix(self.shape)
           else:
              return self
        except:
           return self
     
    def __repr__(self):
        return "ScipyCoo"+str(self.shape)

    def __str__(self):
        return "ScipyCoo"+str(self.shape) + super(ScipyCoo, self).__str__()
     
    @property     
    def isHypre(self):
        return False
     
def convert_to_ScipyCoo(mat):
    if isinstance(mat, np.ndarray):
       mat = coo_matrix(mat)
    if isinstance(mat, spmatrix):
       if not isinstance(mat, coo_matrix):
          mat = mat.tocoo()
       mat.__class__ = ScipyCoo
    return mat

class BlockMatrix(object):
    def __init__(self, shape, kind = default_kind):
        '''
        kind : scipy
                  stores scipy sparse or numpy array
               hypre
        '''
        self.block = [[None]*shape[1] for x in range(shape[0])]
        self.kind  = kind
        self.shape = shape
        self.complex = False

    def __getitem__(self, idx):
        try:
            r, c = idx
        except:
            r = idx ; c = 0
        if isinstance(r, slice):
           new_r = range(self.shape[0])[r]
           ret = BlockMatrix((len(new_r), self.shape[1]))
           for i, r in enumerate(new_r):
              for j in range(self.shape[1]):
                 ret[i, j] = self[r, j]
           return  ret
        elif isinstance(c, slice):
           new_c = range(self.shape[1])[c]
           ret = BlockMatrix((self.shape[0], len(new_c)))
           for i in range(self.shape[0]):
               for j, c in enumerate(new_c):
                 ret[i, j] = self[i, c]
           return  ret
        else:
           return self.block[r][c]

    def __setitem__(self, idx, v):
        try:
            r, c = idx
        except:
            r = idx ; c = 0
        if v is not None:
            if isinstance(v, chypre.CHypreMat):
                pass
            elif isinstance(v, chypre.CHypreVec):
                pass
            elif v is None:
                pass
            else:   
                v = convert_to_ScipyCoo(v)
        
        self.block[r][c] = v
        if np.iscomplexobj(v): self.complex = True

    def __add__(self, v):
        if self.shape != v.shape:
            raise ValueError("Block format is inconsistent")
         
        shape = self.shape
        ret = BlockMatrix(shape, kind = self.kind)
        for i in range(shape[0]):
            for j in range(shape[1]):
                if self[i,j] is None:
                    ret[i,j] = v[i,j]
                elif v[i,j] is None:
                    ret[i,j] = self[i,j]
                else:
                    ret[i,j] = self[i,j] + v[i,j]
        return ret
     
    def __sub__(self, v):
        if self.shape != v.shape:
            raise ValueError("Block format is inconsistent")
        shape = self.shape
        ret = BlockMatrix(shape, kind = self.kind)

        for i in range(shape[0]):
           for j in range(shape[1]):
                if self[i,j] is None:
                    ret[i,j] = -v[i,j]
                elif v[i,j] is None:
                    ret[i,j] = self[i,j]
                else:
                    ret[i,j] = self[i,j] - v[i,j]
        return ret

    def __repr__(self):
        txt = ["BlockMatrix"+str(self.shape)]
        for i in range(self.shape[0]):
           txt.append(str(i) +" : "+ "  ".join([self.block[i][j].__repr__()
                           for j in range(self.shape[1])]))
        return "\n".join(txt)+"\n"


    def format_nnz(self):
        txt = []
        for i in range(self.shape[0]):       
           txt.append(str(i) +" : "+ ",  ".join([str(self[i,j].nnz)
                                                     if hasattr(self[i,j], "nnz") else "unknown"
                                                  for j in range(self.shape[1])]))
        return "non-zero elements (nnz)\n" + "\n".join(txt)
        
    def print_nnz(self):
        print(self.format_nnz())

    def format_true_nnz(self):
        txt = []
        for i in range(self.shape[0]):       
           txt.append(str(i) +" : "+ ",  ".join([str(self[i,j].true_nnz())
                                                     if hasattr(self[i,j], "true_nnz") else "unknown"
                                                  for j in range(self.shape[1])]))
        return "non-zero elements (true nnz)\n" + "\n".join(txt)
     
    def print_true_nnz(self):
        print(self.format_ture_nnz())

    def transpose(self):
        ret = BlockMatrix((self.shape[1], self.shape[0]), kind = self.kind)
        for i in range(self.shape[0]):
            for j in range(self.shape[1]):
                if self[i, j] is not None:
                    ret[j, i] = self[i, j].transpose()
        return ret
     
    def add_to_element(self, i, j, v):
        if self[i,j] is None: self[i,j] = v
        else:
            self[i,j] = self[i,j] + v
            
    def dot(self, mat):
        if self.shape[1] != mat.shape[0]:
            raise ValueError("Block format is inconsistent")

        shape = (self.shape[0], mat.shape[1])
        ret = BlockMatrix(shape, kind = self.kind)

        for i in range(shape[0]):
           for j in range(shape[1]):
               for k in range(self.shape[1]):
                   if self[i, k] is None: continue
                   elif mat[k, j] is None: continue
                   elif ret[i,j] is None:
                       ret[i,j] = self[i, k].dot(mat[k, j])
                   else:
                       ret[i,j] = ret[i,j] + self[i, k].dot(mat[k, j])
                   try:
                       ret[i,j].shape
                   except:
                       ret[i,j] = coo_matrix([[ret[i,j]]]) 
        return ret

    def eliminate_empty_rowcol(self):
        '''
        collect empty row first. (no global communicaiton this step)

        share empty rows..

        apply it to all node

        '''
        from functools import reduce
        ret = BlockMatrix(self.shape, kind = self.kind)        
        P2  = BlockMatrix(self.shape, kind = self.kind)

        dprint1(self.format_true_nnz())

        for i in range(self.shape[0]):
            nonzeros = []
            mat = None
            for j in range(self.shape[1]):
               if self[i,j] is not None:
                   if isinstance(self[i,j], ScipyCoo):
                       coo = self[i,j]
                       csr = coo.tocsr()
                       num_nonzeros = np.diff(csr.indptr)
                       knonzero = np.where(num_nonzeros != 0)[0]
                       if mat is None: mat = coo
                   elif isinstance(self[i,j], chypre.CHypreMat):
                       coo = self[i,j].get_local_coo()
                       if hasattr(coo, "eliminate_zeros"):
                            coo.eliminate_zeros()
                       csr = coo.tocsr()
                       num_nonzeros = np.diff(csr.indptr)
                       knonzero = np.where(num_nonzeros != 0)[0]
                       if mat is None: mat = self[i,j]
                   elif isinstance(self[i,j], chypre.CHypreVec):
                       if self[i,j].isAllZero():
                           knonzero = []
                       else:
                           knonzero = [0]
                   elif (isinstance(self[i,j], np.ndarray) and
                         self[i,j].ndim == 2):
                       knonzero = [k for k in range(self[i,j].shape[0])
                                   if any(self[i,j][k,:])]
                       self[i,j] = convert_to_ScipyCoo(self[i,j])
                       mat = self[i,j]
                   else:
                       raise ValueError("Unsuported Block Element" +
                                        str(type(self[i,j])))
                   nonzeros.append(knonzero)
               else:
                   nonzeros.append([])

            knonzeros = reduce(np.union1d, nonzeros)
            knonzeros = np.array(knonzeros, dtype = np.int64)
            # share nonzero to eliminate column...
            if self.kind == 'hypre':
                if isinstance(self[i,i], chypre.CHypreMat):
                   gknonzeros = self[i,i].GetRowPartArray()[0] + knonzeros
                else:
                   gknonzeros = knonzeros
                gknonzeros = allgather_vector(gknonzeros)
                gknonzeros = np.unique(gknonzeros)
                dprint2('nnz', coo.nnz, len(knonzero))
            else:
                gknonzeros = knonzeros

            if mat is not None:
                # hight and row partitioning of mat is used
                # to construct P2
                if len(gknonzeros) < self[i,i].shape[0]:
                    P2[i,i] = self[i,i].elimination_matrix(gknonzeros)
                else:
                    P2[i,i] = One(self[i,i])
                
            # what if common zero rows differs from common zero col?
            for j in range(self.shape[1]):
                if ret[i,j] is not None:
                    ret[i,j] = ret[i,j].selectRows(gknonzeros)                   
                elif self[i,j] is not None:
                    ret[i,j] = self[i,j].selectRows(gknonzeros)
                else: pass
                if ret[j,i] is not None:
                    ret[j,i] = ret[j,i].selectCols(gknonzeros)                   
                elif self[j,i] is not None:
                    ret[j,i] = self[j,i].selectCols(gknonzeros)
                else: pass
        return ret, P2
     


         
    def reformat_central_mat(self, mat, ksol):
        '''
        reformat central matrix into blockmatrix (columne vector)
        so that matrix can be mumtipleid from the right of this 

        self is a block diagonal matrix
        '''
        L = []
        idx = 0
        ret = BlockMatrix((self.shape[1], 1), kind = self.kind)
        for i in range(self.shape[1]):        
            l = self[i, i].shape[1]
            L.append(l)
            ref = self[i,i]
            if mat is not None:
                v = mat[idx:idx+l, ksol]
            else:
                v = None   # slave node (will recive data)
            idx = idx + l

            ret.set_element_from_central_mat(v, i, 0, ref)

        return ret

    def set_element_from_central_mat(self, v, i, j, ref):
        ''' 
        set element using vector in root node
        row partitioning is taken from column partitioning
        of ref 
        '''
        if self.kind == 'scipy':
            self[i, j] = v.reshape(-1,1)
        else:
            from mpi4py import MPI
            comm = MPI.COMM_WORLD
            
            if ref.isHypre:
                from mpi4py import MPI
                comm = MPI.COMM_WORLD

                part = ref.GetColPartArray()
                v = comm.bcast(v)
                start_row = part[0]
                end_row = part[1]

                v = np.ascontiguousarray(v[start_row:end_row])
                if np.iscomplexobj(v):
                    rv = ToHypreParVec(v.real)    
                    iv = ToHypreParVec(v.imag)    
                    self[i,j] = chypre.CHypreVec(rv, iv)
                else:
                    rv = ToHypreParVec(v)    
                    self[i,j] = chypre.CHypreVec(rv, None)
            else:
                #slave node gets the copy
                v = comm.bcast(v)
                self[i, j] = v.reshape(-1,1)

    def get_squaremat_from_right(self, r, c):
        size = self[r, c].shape
        if self.kind == 'scipy':
            return ScipyCoo((size[1],size[1]))
        else:
            # this will return CHypreMat
            return self[r, c].get_squaremat_from_right()
         
    def gather_densevec(self):
        '''
        gather vector data to head node as dense data (for rhs)
        '''
        if self.kind == 'scipy':
            if self.complex:
                M = scipy.sparse.bmat(self.block, format='coo',
                                      dtype='complex').toarray()
            else:
                M = scipy.sparse.bmat(self.block, format='coo',
                                      dtype='float').toarray()
            return M
        else: 
            data = []
            for i in range(self.shape[0]):
                if isinstance(self[i,0], chypre.CHypreVec):
                    data.append(self[i,0].GlobalVector())
                elif isinstance(self[i,0], np.ndarray):
                    data.append(self[i,0].flatten())
                elif isinstance(self[i,0], ScipyCoo):
                    data.append(self[i,0].toarray().flatten())
                else:
                    raise ValueError("Unsupported element" + str((i,0)) + 
                                     ":" + str(type(self[i,0])))
            return np.hstack(data).reshape(-1,1)
        
    def get_global_coo(self, dtype = 'float'):
        '''
        build matrix in coordinate format
        '''
        roffset = []
        coffset = []
        for i in range(self.shape[0]):
            for j in range(self.shape[1]):
                if self[i, j] is not None:
                   roffset.append(self[i,j].shape[0])
                   break
        for j in range(self.shape[1]):
            for i in range(self.shape[0]):
                if self[i, j] is not None:
                   coffset.append(self[i,j].shape[1])
                   break
        #coffset = [self[0, j].shape[1] for j in range(self.shape[1])] 
        roffsets = np.hstack([0, np.cumsum(roffset)])
        coffsets = np.hstack([0, np.cumsum(coffset)])
        col = []
        row = []
        data = []
        glcoo = coo_matrix((roffsets[-1], coffsets[-1]), dtype = dtype)
        dprint1("roffset", roffsets)
        for i in range(self.shape[0]):
            for j in range(self.shape[1]):
                if self[i,j] is None: continue
                gcoo = self[i,j].get_global_coo()
                dprint1(i, j, len(gcoo.row))
                row.append(gcoo.row + roffsets[i])                
                col.append(gcoo.col + coffsets[j])
                data.append(gcoo.data)
        glcoo.col = np.hstack(col)
        glcoo.row = np.hstack(row)
        glcoo.data = np.hstack(data)

        return glcoo



                
        
          
            



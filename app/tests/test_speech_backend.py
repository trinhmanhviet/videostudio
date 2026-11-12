import os,sys,tempfile,types,unittest
from unittest.mock import Mock,patch
from videostudio import speech_worker as sw


class SpeechBackendTests(unittest.TestCase):
    def load(self,*,cuda=True,missing=False,backend=None,device=None):
        torch=types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=Mock(return_value=cuda)))
        factory=Mock(side_effect=lambda **kwargs:types.SimpleNamespace(backend=kwargs['backend']))
        original=Mock(name='original_session',spec=[])
        ort=types.SimpleNamespace(InferenceSession=original,get_available_providers=lambda:['CUDAExecutionProvider','CPUExecutionProvider'])
        modules={'torch':None if missing else torch,'vieneu':types.SimpleNamespace(Vieneu=factory),'onnxruntime':ort}
        env={}
        if backend is not None:env['VS_SPEECH_BACKEND']=backend
        if device is not None:env['VS_SPEECH_DEVICE']=device
        with tempfile.TemporaryDirectory() as cache,patch.dict(os.environ,env,clear=True),patch.dict(sys.modules,modules),patch.object(sw,'_add_onnx_dlls',create=True) as dll:
            model=sw.load_model(cache)
            offline=os.environ.get('HF_HUB_OFFLINE')
        return model,factory,dll,ort,original,offline

    def test_auto_prefers_pytorch_cuda_without_comfy_dll_or_ort_patch(self):
        model,factory,dll,ort,original,offline=self.load()
        self.assertEqual(model.backend,'pytorch')
        self.assertEqual(factory.call_args.kwargs['device'],'cuda')
        dll.assert_not_called();self.assertIs(ort.InferenceSession,original)
        self.assertEqual(offline,'1')

    def test_missing_torch_or_cuda_falls_back_to_onnx(self):
        for kwargs in ({'missing':True},{'cuda':False},{'backend':'pytorch','missing':True},{'backend':'pytorch','cuda':False}):
            model,*_=self.load(**kwargs)
            self.assertEqual(model.backend,'onnx')

    def test_force_onnx_keeps_the_existing_cuda_provider_path(self):
        model,_,dll,ort,original,_=self.load(backend='onnx')
        self.assertEqual(model.backend,'onnx');dll.assert_called_once()
        with patch.dict(os.environ,{},clear=True):ort.InferenceSession('model',providers=['CPUExecutionProvider'])
        self.assertEqual(original.call_args.kwargs['providers'],['CUDAExecutionProvider','CPUExecutionProvider'])

    def test_cpu_override_wins_and_does_not_add_cuda_dlls(self):
        for backend in (None,'onnx','pytorch'):
            model,factory,dll,ort,original,_=self.load(backend=backend,device='cpu')
            self.assertEqual(model.backend,'onnx');dll.assert_not_called()
            with patch.dict(os.environ,{'VS_SPEECH_DEVICE':'cpu'},clear=True):ort.InferenceSession('model',providers=['CPUExecutionProvider'])
            self.assertEqual(original.call_args.kwargs['providers'],['CPUExecutionProvider'])

    def test_invalid_backend_is_reported(self):
        with self.assertRaises(ValueError):self.load(backend='typo')

    def test_cpu_override_is_normalized_consistently(self):
        _,_,dll,ort,original,_=self.load(device=' CPU ')
        dll.assert_not_called()
        with patch.dict(os.environ,{'VS_SPEECH_DEVICE':' CPU '},clear=True):ort.InferenceSession('model',providers=['CPUExecutionProvider'])
        self.assertEqual(original.call_args.kwargs['providers'],['CPUExecutionProvider'])

    def test_wrapping_ort_twice_does_not_stack_and_respects_explicit_providers(self):
        _,_,_,ort,original,_=self.load(backend='onnx')
        self.assertIs(getattr(ort.InferenceSession,'_vs_original',None),original)
        ort.InferenceSession('model',providers=['SomeOtherProvider'])
        self.assertEqual(original.call_args.kwargs['providers'],['SomeOtherProvider'])

if __name__=='__main__':unittest.main()

# Troubleshooting

This section aims to provide helpful tips and suggestions for commonly found errors.

## Common Issues


### sdg-op task fails with error 'The model `text-classifier-knowledge-v3-clm` does not exist.'

Example trace:

```text
File "/opt/app-root/lib64/python3.11/site-packages/instructlab/sdg/pipeline.py", line 237, in _generate_single
raise PipelineBlockError(
instructlab.sdg.pipeline.PipelineBlockError: PipelineBlockError(<class 'instructlab.sdg.blocks.llmblock.LLMBlock'>/router): Error code: 404 - {'object': 'error', 'message': 'The model `text-classifier-knowledge-v3-clm` does not exist.', 'type': 'NotFoundError', 'param': None, 'code': 404}
Failed to set precomputed skills data ratio: PipelineBlockError(<class 'instructlab.sdg.blocks.llmblock.LLMBlock'>/router): Error code: 404 - {'object': 'error', 'message': 'The model `text-classifier-knowledge-v3-clm` does not exist.', 'type': 'NotFoundError', 'param': None, 'code': 404}
I0325 16:58:41.335956 98 launcher_v2.go:193] publish success.
I0325 16:58:41.394021 98 client.go:752] Attempting to update DAG state
I0325 16:58:41.568621 98 launcher_v2.go:157] Stopping Modelcar container for artifact oci://quay.io/opendatahub/ds-pipelines-runtime-generic@sha256:f53e53a39b1a88c3a530e87ded473ba2648b8d8586ec9e31a4484e9bafb3059d
F0325 16:58:41.568909 98 main.go:54] failed to execute component: exit status 1
time="2025-03-25T16:58:42.294Z" level=info msg="sub-process exited" argo=true error="<nil>"
Error: exit status 1
```

This error happens when running the pipeline in agentic mode (pipeline parameter `sdg_pipeline` is set to `/usr/share/instructlab/sdg/pipelines/agentic`) but the LoRA adapters are not available in the teacher model

Solution: enable the LORA adapters in the teacher model or run the pipeline with Full synthetic data generation (`sdg_pipeline=full`)

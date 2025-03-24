### Updating the Pipeline

The Pipeline code can be found in `pipeline.py` as well as the various component directories (e.g. `sdg`, `eval`, etc.).

Once any change is made, you will need to update the rendered Pipeline IR by doing the following:

```bash
make pipeline
```

This will update the `pipeline.yaml` file at the root directory.

## Developer setup

To collaborate on this repository, please follow these steps:

1. Install [uv]
2. Run following commands to prepare your local environment
    ```bash
    uv sync
    source .venv/bin/activate
    ```

[uv]: https://docs.astral.sh/uv/getting-started/installation/

## Adding/Updating dependencies

When updating python package dependencies in `pyproject.toml`, regenerate [requirements.txt]:

```
uv pip compile pyproject.toml --generate-hashes > requirements.txt
```

To regenerate [requirements-build.txt] is currently a manual step.
For this you need [pybuild-deps] installed.

Temporarily remove `kfp-pipeline-spec` from `requirement.txt`. And run:

```bash
pybuild-deps compile requirements.txt -o requirements-build.txt
```

> Note that, we do this because `kfp-pipeline-spec` only includes wheels and not the sources, this breaks
> `pybuild-deps`, in the future we will need to a workaround (or get the package to include sdist) to automate this.

##### Suggested Parameters: Development

Running the ilab pipeline at full capabilities takes a very long time, and with a good amount of resource consumption.
To create an e2e run that completes much quicker (at the expense of output quality), and with fewer resources (namely, GPU nodes) we suggest using these values instead:

| Parameter                            | Suggested Value                                                  |
|--------------------------------------|------------------------------------------------------------------|
| eval_gpu_identifier                  | nvidia.com/gpu                                                   |
| eval_judge_secret                    | judge-secret                                                     |
| final_eval_batch_size                | auto                                                             |
| final_eval_few_shots                 | 5                                                                |
| final_eval_max_workers               | auto                                                             |
| final_eval_merge_system_user_message | False                                                            |
| k8s_storage_class_name               | nfs-csi                                                          |
| k8s_storage_size                     | 100Gi                                                            |
| mt_bench_max_workers                 | auto                                                             |
| mt_bench_merge_system_user_message   | False                                                            |
| output_model_name                    | test-model-name                                                  |
| output_model_registry_api_url        | https://your-model-registry-url.com                              |
| output_model_registry_name           | <empty-value>                                                    |
| output_model_version                 | v1.0                                                             |
| output_modelcar_base_image           | registry.access.redhat.com/ubi9-micro:latest                     |
| output_oci_model_uri                 | oci://your-oci-registry                                          |
| output_oci_registry_secret           | output-oci-registry-secret                                       |
| sdg_base_model                       | oci://registry.redhat.io/rhelai1/modelcar-granite-7b-starter:1.4 |
| sdg_batch_size                       | 128                                                              |
| sdg_max_batch_len                    | 5000                                                             |
| sdg_num_workers                      | 2                                                                |
| sdg_pipeline                         | simple                                                           |
| sdg_repo_branch                      | <empty-value>                                                    |
| sdg_repo_pr                          | 0                                                                |
| sdg_repo_secret                      | <empty-value>                                                    |
| sdg_repo_url                         | https://github.com/instructlab/taxonomy.git                      |
| sdg_sample_size                      | 0.0002                                                           |
| sdg_scale_factor                     | 2                                                                |
| sdg_teacher_secret                   | teacher-secret                                                   |
| train_cpu_per_worker                 | 4                                                                |
| train_effective_batch_size_phase_1   | 128                                                              |
| train_effective_batch_size_phase_2   | 3840                                                             |
| train_gpu_identifier                 | nvidia.com/gpu                                                   |
| train_gpu_per_worker                 | 1                                                                |
| train_learning_rate_phase_1          | 0.00002                                                          |
| train_learning_rate_phase_2          | 0.000006                                                         |
| train_max_batch_len                  | 5000                                                             |
| train_memory_per_worker              | 100Gi                                                            |
| train_node_selectors                 | {}                                                               |
| train_num_epochs_phase_1             | 1                                                                |
| train_num_epochs_phase_2             | 1                                                                |
| train_num_warmup_steps_phase_1       | 100                                                              |
| train_num_warmup_steps_phase_2       | 100                                                              |
| train_num_workers                    | 2                                                                |
| train_save_samples                   | 0                                                                |
| train_seed                           | 42                                                               |
| train_tolerations                    | []                                                               |

Using these parameters will allow a user to run the complete pipeline much quicker; in testing we have found this to take about 90 minutes.
Additionally, we can point the `judge-server` and `teacher-server` to the same Mistral model, which only uses 1 GPU, and the PyTorchJob configuration specified here also only uses 2 training nodes of 1 GPU, so a total of 3 GPUs are required, rather than the 8-9 GPUs required for the full pipeline.

With that said, the output model quality is likely very poor, and these should only be used for testing purposes.

Note also the above parameters assume you are using an [nfs storage]. You will also need to sub in values where needed
(i.e. judge/teacher secrets, oci push secret, etc.)

[requirements.txt]: requirements.txt
[pybuild-deps]: https://pybuild-deps.readthedocs.io/en/latest/usage.html#pybuild-deps-compile
[nfs storage]: ./manifests/nfs_storage/nfs_storage.md

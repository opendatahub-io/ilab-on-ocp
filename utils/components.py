# type: ignore

from kfp import dsl

from .consts import RHELAI_IMAGE, TOOLBOX_IMAGE


@dsl.component(base_image=RHELAI_IMAGE, install_kfp_package=False)
def mock_op():
    pass


@dsl.container_component
def pvc_to_mt_bench_op(mt_bench_output: dsl.Output[dsl.Artifact], pvc_path: str):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {mt_bench_output.path}"],
    )


@dsl.container_component
def pvc_to_mt_bench_branch_op(
    mt_bench_branch_output: dsl.Output[dsl.Artifact], pvc_path: str
):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {mt_bench_branch_output.path}"],
    )


@dsl.container_component
def pvc_to_mmlu_branch_op(mmlu_branch_output: dsl.Output[dsl.Artifact], pvc_path: str):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {mmlu_branch_output.path}"],
    )


@dsl.container_component
def pvc_to_model_op(model: dsl.Output[dsl.Model], pvc_path: str):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {model.path}"],
    )


@dsl.container_component
def model_to_pvc_op(model: dsl.Input[dsl.Model], pvc_path: str = "/model"):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {model.path}/* {pvc_path}"],
    )

@dsl.container_component
def tarball_to_pvc_op(tarball_location: dsl.Input[dsl.Dataset], pvc_path: str = "/data", tarball_filename: str = ""):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [
            f"cp {tarball_location.path} {pvc_path}/ && if [ ! -z '{tarball_filename}' ]; then tar -xvzf {pvc_path}/{tarball_filename} -C {pvc_path}; fi",
        ],
    )


@dsl.container_component
def ilab_importer_op(repository: str, release: str, base_model: dsl.Output[dsl.Model]):
    return dsl.ContainerSpec(
        RHELAI_IMAGE,
        ["/bin/sh", "-c"],
        [
            f"ilab --config=DEFAULT model download --repository {repository} --release {release} --model-dir {base_model.path}"
        ],
    )

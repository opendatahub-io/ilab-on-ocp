## prometheus serving (Judge Model)

Prometheus is required as part of the Instructlab process for model judgement. The following will describe how to provide prometheus.

### Serving Namespace

Switch to the namespace you will be deploying your model for serving:

```
oc project <your-namespace>
```

We will deploy all necessary manifests to this namespace.

### Secret
Because we neet to run oras inside of a container to download the various artifacts we must provide a .dockerconfigjson to the Kubernetes job with authentication back to registry.redhat.io.
It is suggested to use a Service account. https://access.redhat.com/terms-based-registry/accounts is the location to create a service account.

Create a secret based off of the service account.

secret.yaml

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: 7033380-ilab-pull-secret
stringData:
  .dockerconfigjson: { ... }
type: kubernetes.io/dockerconfigjson
```

Create the secret

```bash
oc create -f secret.yaml
```

### Kubernetes Job
Depending on the name of your secret the file `../prometheus_pull/pull_kube_job.yaml` will need to be modified.

```yaml
      - name: docker-config
        secret:
          secretName: 7033380-ilab-pull-secret
```

With the secretName now reflecting your secret the job can be launched.

```bash
oc create -f ./prometheus_pull
```

This will create 3 different containers downloading various things using oras.

### Deploy the InferenceService and ServingRuntime

Deploy the Prometheus Serving Runtime and Inference Service

```bash
oc create -f ./prometheus_serve
```

Follow the log of the kserve-container and wait for the the following log entry

```
INFO: Waiting for application startup.
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

For the ILAB Pipeline you will need to retrieve the following: `api_token`, `endpoint`, and `model_name`.

The `model_name` is always `prometheus`.
The `api_token` can be retrieved by running the following:

```bash
api_token=$(oc create token prometheus-sa)
```

And `endpoint` can be retrieved via:

```bash
# If you don't have yq, omit the pipe and inspect the .status.url field manually

endpoint=$(oc get ksvc prometheus-predictor -o yaml | yq .status.url)/v1
```

### Testing
Using curl you can ensure that the model is accepting connections

```bash
curl -X POST "${endpoint}/completions" -H  "Authorization: Bearer ${api_token}" \
        -H "Content-Type: application/json" -d '{"model": "prometheus", "prompt": "San Francisco is a", "max_tokens": 7, "temperature": 0 }'


{"id":"cmpl-ecd5bd72a947438b805e25134bbdf636","object":"text_completion","created":1730231625,"model":"prometheus","choices":[{"index":0,"text":" city that is known for its steep","logprobs":null,"finish_reason":"length","stop_reason":null,"prompt_logprobs":null}],"usage":{"prompt_tokens":5,"total_tokens":12,"completion_tokens":7}}%
```

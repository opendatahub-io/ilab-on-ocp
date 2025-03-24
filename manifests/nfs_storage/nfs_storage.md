# Setup NFS StorageClass

The InstructLab Pipeline requires [ReadWriteMany] support for `PersistentVolumes`.

If you do not have this, a quick way to get this set up is via NFS. The instructions
below will guide you on how you may leverage your own NFS server deployment.

The end result will be a StorageClass, which you will then provide to the InstructLab
pipeline in the form of an input for the `k8s_storage_class_name` parameter.

> [!CAUTION]
> The image provided here is for test purposes only.
> For production, users must provide a production ready StorageClass with ReadWriteMany capability.

This step is needed when the cluster doesn't have a storage provisioner capable of provisioning PersistentVolumeClaim with ReadWriteMany capability.

Installing the NFS CSI driver
```bash
$ curl -skSL https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/v4.9.0/deploy/install-driver.sh | bash -s v4.9.0 --
```

For deploying an in-cluster NFS server, apply [nfs-server-deployment.yaml] file

```bash
oc new-project nfs
oc apply -f ./nfs_storage/nfs-server-deployment.yaml
```

> [!NOTE]
> Note:  Check the root PersistentVolumeClaim that'll be created and the requested storage.

For creating NFS storage-class, apply [nfs-storage-class.yaml] file
```bash
oc apply -f ./nfs_storage/nfs_storage-class.yaml
```

[nfs-storage-class.yaml]:/manifests/nfs-storageyaml/nfs-storage/nfs-storage-class.yaml
[nfs-server-deployment.yaml]:/manifests/nfs-storageyaml/nfs-storage/nfs-server-deployment.yaml
[ReadWriteMany]: https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes

#!/bin/bash
#SBATCH --job-name=fz-openqa
#SBATCH --output=./slurm/%j.out
#SBATCH --ntasks=1 --cpus-per-task=16 --mem=64G
#SBATCH -p gpu --gres=gpu:titanrtx:4
#SBATCH --time=3-00:00:00


for i in "$@"; do
  case $i in
    -e=*|--dset_name=*)
      DSET_NAME="${i#*=}"
      shift # past argument=value
      ;;
    -s=*|--corpus_name=*)
      CORPUS_NAME="${i#*=}"
      shift # past argument=value
      ;;
    --gradients)
      GRADIENTS="${i#*=}"
      shift # past argument with no value
      ;;
    -*|--*)
      echo "Unknown option $i"
      exit 1
      ;;
    *)
      ;;
  esac
done

echo "===================================="
echo "DSET_NAME    = ${DSET_NAME}"
echo "CORPUS_NAME  = ${CORPUS_NAME}"
echo "GRADIENTS    = ${GRADIENTS}"
echo "===================================="
# variables
setup_with_model=false

# display basic info
hostname
echo $CUDA_VISIBLE_DEVICES
echo "===================================="
poetry run gpustat --debug
echo "====== starting experiment ========="

# startup elastic search
if [ "$setup_with_model" = false ]
then
    elasticsearch --quiet &
fi

# run the model
poetry run python run.py +experiment=option_retriever +environ=diku \
  +patch=dpr \
  model/module/gradients=${GRADIENTS} \
  base.device_batch_size=1 \
  base.infer_batch_mul=10 \
  datamodule.dset_name=${DSET_NAME} \
  datamodule.dset_name=${CORPUS_NAME} \
  base.eval_device_batch_size=4 \
  trainer.precision=32 \
  datamodule.num_workers=8 \
  +setup_with_model=${setup_with_model} \
  +kill_es=true

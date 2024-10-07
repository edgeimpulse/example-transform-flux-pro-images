FROM ubuntu:20.04

WORKDIR /app

RUN apt update && apt install -y python3 python3-distutils wget
RUN wget https://bootstrap.pypa.io/get-pip.py && \
    python3.8 get-pip.py "pip==21.3.1" && \
    rm get-pip.py

# Python dependencies
COPY requirements.txt ./
RUN pip3 --no-cache-dir install -r requirements.txt

COPY . ./

ENV CUDA_LAUNCH_BLOCKING=1

ENV TORCH_USE_CUDA_DSA=1

ENTRYPOINT [ "python3",  "transform.py" ]
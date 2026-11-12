# Portable image for reavectors. Runs anywhere Docker runs (laptop, VPS, Render).
#
#   docker build -t reavectors .
#   docker run -p 8756:8756 --env-file .env reavectors
#
FROM python:3.12-slim

# No .pyc on disk (keeps images/volumes tidy) and single-threaded BLAS (small RAM).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8756
CMD ["python", "-m", "reavectors.server"]

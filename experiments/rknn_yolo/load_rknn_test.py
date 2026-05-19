from rknnlite.api import RKNNLite

MODEL_PATH = "models/yolo26n_fp32.rknn"

def main():
    rknn = RKNNLite()

    print("[1/3] Load RKNN model...")
    ret = rknn.load_rknn(MODEL_PATH)
    if ret != 0:
        raise RuntimeError(f"load_rknn failed, ret={ret}")

    print("[2/3] Init runtime...")
    ret = rknn.init_runtime()
    if ret != 0:
        raise RuntimeError(f"init_runtime failed, ret={ret}")

    print("[3/3] Release...")
    rknn.release()

    print("RKNN model load/init OK")

if __name__ == "__main__":
    main()

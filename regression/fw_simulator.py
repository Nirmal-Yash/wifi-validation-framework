"""Reference fake firmware/device simulator for adapter contract testing."""
import argparse
import hashlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.adapters import FakeDeviceAdapter, FakeFirmwareAdapter, FirmwareAuthorization, FirmwareImage
from lib.services.firmware_service import FirmwareOperationService

def main() -> int:
    parser=argparse.ArgumentParser(description='Run the hardware-free firmware adapter simulator')
    parser.add_argument('--version',default='v2.0')
    parser.add_argument('--bug',choices=['dns','dhcp','ssid','latency','flash','reboot','incompatible','rollback'],default=None)
    parser.add_argument('--restore',action='store_true')
    args=parser.parse_args()
    if args.restore:
        print('Simulator restore: no real lab state is changed.')
        return 0
    if args.bug in {'dns','dhcp','ssid','latency'}:
        print(f'Legacy simulator bug label accepted: {args.bug}; adapter simulator does not mutate the real lab.')
        args.bug=None
    scenario={'flash':'flash_failure','reboot':'reboot_failure'}.get(args.bug,'nominal')
    device=FakeDeviceAdapter(scenario=scenario); adapter=FakeFirmwareAdapter(device); service=FirmwareOperationService()
    image_path=Path(__file__).resolve().parent/'_simulator_firmware.bin'
    image_path.write_bytes(('netregress-simulator-'+args.version).encode())
    try:
        models=('other-model',) if args.bug=='incompatible' else ('simulator',)
        content=image_path.read_bytes()
        image=FirmwareImage.from_path(image_path,version=args.version,compatible_models=models,expected_sha256=hashlib.sha256(content).hexdigest())
        authorization=FirmwareAuthorization('fw_simulator','explicit simulator operation',True,'FLASH')
        result=service.update(adapter=adapter,image=image,authorization=authorization)
        print(f'Simulator firmware update completed: {result.verified_version}')
        if args.bug=='rollback':
            adapter.rollback(authorization=FirmwareAuthorization('fw_simulator','explicit simulator rollback',True,'ROLLBACK'))
            print(f'Simulator rollback completed: {device.firmware_version}')
        return 0
    finally:
        image_path.unlink(missing_ok=True)

if __name__=='__main__': raise SystemExit(main())
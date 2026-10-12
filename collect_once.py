import argparse
import json
import sys
from collector import SlackCollector
from coordinator import Coordinator

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--commons-runtime', required=True)
    parser.add_argument('--database', required=True)
    args = parser.parse_args()
    sys.path.insert(0, args.commons_runtime)
    from integrations.shared_equipment.services import ServiceEquipment
    result = SlackCollector(Coordinator(args.database), ServiceEquipment()).tick()
    print(json.dumps(result))

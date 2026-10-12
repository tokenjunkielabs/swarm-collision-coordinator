"""Narrow install adapter for existing shared ServiceEquipment, remote authority."""
from cloud_client import CloudCoordinator
from equipment_adapter import CoordinatedCatalog

class RawEquipment:
    def __init__(self,equipment):self.equipment=equipment
    def __getattr__(self,name):return getattr(self.equipment,name)
    def call(self,name,arguments):return self.equipment._uncoordinated_call(name,arguments)
    def tools(self,**kwargs):return self.equipment._uncoordinated_tools(**kwargs)

def catalog(equipment):
    existing=getattr(equipment,'_collision_coordination',None)
    if existing is None:
        from integrations.shared_equipment.credential_transfer import CredentialSources
        source=CredentialSources()
        existing=CoordinatedCatalog(RawEquipment(equipment),CloudCoordinator(lambda:source.read('github/tokenjunkielabs')))
        equipment._collision_coordination=existing
    return existing

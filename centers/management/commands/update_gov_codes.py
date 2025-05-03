import os
from django.core.management.base import BaseCommand
from centers.models import Governorate, Delegation

GOVERNORATE_CODES =  {
    'Tunis': 11,
    'Ariana': 12,
    'Ben Arous': 13,
    'Manouba': 14,
    'Nabeul': 21,
    'Zaghouan': 22,
    'Bizerte': 23,
    'Béja': 31,
    'Jendouba': 32,
    'Le Kef': 33,
    'Siliana': 34,
    'Kairouan': 41,
    'Kassérine': 42,
    'Sidi Bouzid': 43,
    'Sousse': 51,
    'Monastir': 52,
    'Mahdia': 53,
    'Sfax': 61,
    'Gafsa': 71,
    'Tozeur': 72,
    'Kebili': 73,
    'Gabès': 81,
    'Médenine': 82,
    'Tataouine': 83
}

DELEGATION_CODES ={
    "Ariana Medina": 12001,
    "Ettadhamen": 12003,
    "Mnihla": 12002,
    "Raoued": 12005,
    "Ben Arous": 13001,
    "Bou Mhel El Bassatine": 13002,
    "El Mourouj": 13003,
    "Fouchana": 13005,
    "Hammam Lif": 13007,
    "Megrine": 13008,
    "Mornag": 13010,
    "La Nouvelle Medina": 13011,
    "Douar Hicher": 14002,
    "Manouba": 14005,
    "Tebourba": 14008,
    "Grombalia": 21007,
    "Hammamet": 21009,
    "Kélibia": 21010,
    "Korba": 21011,
    "Menzel Bouzelfa": 21012,
    "Menzel Temime": 21013,
    "Nabeul": 21014,
    "Soliman": 21015,
    "El Fahs": 22002,
    "Zaghouan": 22005,
    "Bizerte Nord": 23001,
    "El Alia": 23003,
    "Ghar El Melh": 23004,
    "Mateur": 23007,
    "Menzel Bourguiba": 23008,
    "Ras Jabel": 23010,
    "Sejenane": 23012,
    "Béja Nord": 31002,
    "Medjez El Bab": 31005,
    "Bou Salem": 32003,
    "Ghardimaou": 32005,
    "Jendouba": 32006,
    "Jendouba Nord": 32007,
    "Tabarka": 32009,
    "Kef Est": 33002,
    "Kef Ouest": 33003,
    "Tajerouine": 33011,
    "Makthar": 34007,
    "Siliana Sud": 34011,
    "Haffouz": 41006,
    "Kairouan Nord": 41008,
    "Kasserine Nord": 42008,
    "Sbeïtla": 42011,
    "Thala": 42013,
    "Meknassy": 43004,
    "Regueb": 43007,
    "Sidi Bouzid Est": 43011,
    "Sidi Bouzid Ouest": 43012,
    "Enfida": 51003,
    "M'saken": 51009,
    "Sidi Bou Ali": 51010,
    "Sousse Jawhara": 51013,
    "Jemmal": 52004,
    "Ksar Hellal": 52005,
    "Moknine": 52007,
    "Monastir": 52008,
    "Chebba": 53003,
    "El Djem": 53005,
    "Ksour Essef": 53007,
    "Mahdia": 53008,
    "Souassi": 53011,
    "Bir Ali Ben Khalifa": 61002,
    "Mahres": 61005,
    "Jebiniana": 61007,
    "Kerkennah": 61008,
    "Sakiet Eddaïer": 61010,
    "Sakiet Ezzit": 61011,
    "Sfax Ville": 61012,
    "Sfax Ouest": 61013,
    "Sfax Sud": 61014,
    "Gafsa Sud": 71005,
    "Mdhilla (assumed Moulares if typo)": 71008,
    "Sned (assumed Sened if typo)": 71010,
    "Tozeur": 72006,
    "Douz South": 73002,
    "Kebili North": 73004,
    "Kebili South": 73005,
    "El Hamma": 81002,
    "Gabes Medina": 81004,
    "Gabes Sud": 81006,
    "Mareth": 81009,
    "Ben Guerdane": 82001,
    "Beni Khedech": 82002,
    "Djerba Houmet Souk": 82004,
    "Djerba Midoun": 82005,
    "Médenine Nord": 82006,
    "Médenine Sur": 82007,
    "Zarzis": 82009,
    "Tataouine Nord": 83007
}


class Command(BaseCommand):
    help = 'Updates governorate and delegation codes with official numeric codes'

    def handle(self, *args, **options):
        # Update Governorate codes
        for name, code in GOVERNORATE_CODES.items():
            updated = Governorate.objects.filter(name__iexact=name).update(code=code)
            if updated:
                self.stdout.write(f"Updated {name} with code {code}")
            else:
                self.stdout.write(f"Governorate {name} not found", style='WARNING')

        # Update Delegation codes
        for name, code in DELEGATION_CODES.items():
            updated = Delegation.objects.filter(name__iexact=name).update(code=code)
            if updated:
                self.stdout.write(f"Updated {name} with code {code}")
            else:
                self.stdout.write(f"Delegation {name} not found", style='WARNING')

        self.stdout.write("Code update completed!", style='SUCCESS')
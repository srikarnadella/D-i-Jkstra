
from enum import Enum
class TransitionType(Enum):
    SMOOTH = "Smooth"
    AGGRESSIVE = "Aggressive"
    SUDDEN = "Sudden"
    GRADUAL = "Gradual"


class SongEdge:
    idcounter = 1

    def __init__(self, transition_type, notes, source, destination):
        self.id = SongEdge.idcounter
        SongEdge.idcounter += 1

        self.transition_type = transition_type
        self.notes = notes
        self.source = source
        self.destination = destination

    def __str__(self):
        return f"Edge ID: {self.id}\n" \
               f"Transition: {self.transition_type.value}\n" \
               f"Notes: {self.notes}\n" \
               f"Source Song: {self.source.name} (ID: {self.source.id})\n" \
               f"Destination Song: {self.destination.name} (ID: {self.destination.id})\n" \



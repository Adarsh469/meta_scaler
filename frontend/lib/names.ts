// Deterministic patient display names seeded from case_id
// so the same case always shows the same name.

const MALE_NAMES = [
    "James Carter", "Liam Patel", "Noah Rivera", "Ethan Brooks", "Mason Kim",
    "Oliver Chen", "Aiden Walsh", "Lucas Nguyen", "Henry Scott", "Jack Torres",
    "Sebastian Flores", "Daniel Park", "Owen Reyes", "Logan Davis", "Ryan Murphy",
    "Nathan Hughes", "Caleb Foster", "Isaac Bell", "Eli Ward", "Aaron Diaz",
    "Adrian Morales", "Jayden Cooper", "Cameron Reed", "Dominic Gray", "Evan Price",
];

const FEMALE_NAMES = [
    "Emma Johnson", "Olivia Martinez", "Ava Thompson", "Sophia Lee", "Isabella Clark",
    "Mia Walker", "Charlotte Hall", "Amelia Allen", "Harper Young", "Evelyn Hill",
    "Abigail Baker", "Emily Nelson", "Ella Mitchell", "Elizabeth Carter", "Chloe Perez",
    "Victoria Roberts", "Grace Turner", "Lily Phillips", "Scarlett Campbell", "Zoey Evans",
    "Hannah Collins", "Nora Sanchez", "Lily Morris", "Aria Rogers", "Penelope Reed",
];

/** Seed a simple hash from the case_id string so the name is stable across renders. */
function hashCode(str: string): number {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        hash = (hash * 31 + str.charCodeAt(i)) >>> 0;
    }
    return hash;
}

export function getPatientName(case_id: string, gender: string): string {
    const h = hashCode(case_id);
    if (gender === "female") {
        return FEMALE_NAMES[h % FEMALE_NAMES.length];
    }
    return MALE_NAMES[h % MALE_NAMES.length];
}

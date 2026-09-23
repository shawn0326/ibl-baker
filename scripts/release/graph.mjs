function identity(value) {
    return value.registry + ':' + value.name + '@' + value.version;
}

function dependencyIdentity(value) {
    return identity(value);
}

function compare(a, b) {
    const left = identity(a), right = identity(b);
    return left < right ? -1 : left > right ? 1 : 0;
}

export function packageIdentity(value) {
    return identity(value);
}

export function orderPackages(packages) {
    const nodes = new Map();
    for (const pkg of packages) {
        const key = identity(pkg);
        if (nodes.has(key)) throw new Error('Duplicate release package: ' + key);
        nodes.set(key, { pkg, dependencies: new Set(), dependents: new Set(), remaining: 0 });
    }

    for (const node of nodes.values()) {
        for (const dependency of node.pkg.dependencies ?? []) {
            const dependencyKey = dependencyIdentity(dependency);
            const target = nodes.get(dependencyKey);
            if (!target) throw new Error('Missing release dependency: ' + dependencyKey + ' required by ' + identity(node.pkg));
            if (node.dependencies.has(dependencyKey)) continue;
            node.dependencies.add(dependencyKey);
            target.dependents.add(identity(node.pkg));
        }
        node.remaining = node.dependencies.size;
    }

    const ready = [...nodes.values()].filter(node => node.remaining === 0).sort((a, b) => compare(a.pkg, b.pkg));
    const ordered = [];
    while (ready.length) {
        const node = ready.shift();
        ordered.push(node.pkg);
        for (const dependentKey of [...node.dependents].sort((a, b) => a < b ? -1 : a > b ? 1 : 0)) {
            const dependent = nodes.get(dependentKey);
            dependent.remaining--;
            if (dependent.remaining === 0) {
                ready.push(dependent);
                ready.sort((a, b) => compare(a.pkg, b.pkg));
            }
        }
    }

    if (ordered.length !== nodes.size) {
        const cycle = [...nodes.values()].filter(node => node.remaining > 0).map(node => identity(node.pkg)).sort();
        throw new Error('Release package dependency cycle: ' + cycle.join(', '));
    }
    return ordered;
}

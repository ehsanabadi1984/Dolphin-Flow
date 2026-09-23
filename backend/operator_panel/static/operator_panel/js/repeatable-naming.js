function reindexRepeatableFieldName(oldName, groupPrefix, newIndex) {
    if (!oldName.startsWith(groupPrefix)) {
        return oldName;
    }

    const remainder = oldName.slice(groupPrefix.length);
    const separatorIndex = remainder.indexOf("_");

    if (separatorIndex === -1) {
        return oldName;
    }

    return (
        groupPrefix +
        String(newIndex) +
        remainder.slice(separatorIndex)
    );
}

function buildRepeatableGroupPrefix(parentContext, groupCode) {
    return (
        parentContext
            .map(({ groupCode, index }) => `${groupCode}_${index}_`)
            .join("") +
        groupCode +
        "_"
    );
}

globalThis.DolphinFlowRepeatableNaming = {
    reindexRepeatableFieldName,
    buildRepeatableGroupPrefix,
};

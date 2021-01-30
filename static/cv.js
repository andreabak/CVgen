import {html, render} from 'https://unpkg.com/lit-html?module';


const intBool = value => value ? 1 : 0;


const sectionTemplate = (data) => html`
    <section id="${data.id}">${data.inner}</section>`;
const headerSectionTemplate = (data) => html`
    <span id="name">${data.name}</span><span id="nickname">${data.nickname}</span>
    <div id="contacts">${data.contacts}</div>`;
const textSectionTemplate = (data) => html`
    <h2>${data.title}</h2>
    <p id="${data.id}Text" class="text">${data.text}</p>`;
const listSectionTemplate = (data) => html`
    <h2>${data.title}</h2>
    <div id="${data.id}List">${data.content}</div>`;
const skillsSectionTemplate = (data) => html`
    <h2>${data.title}</h2>
    <div id="${data.id}List" class="tiered">${data.content}</div>`;

const contactTemplate = (data) => html`
    <a class="contact" title="${data.type}: ${data.contact}" href="${data.href}"
            target="_blank"
            data-onlyicon="${intBool(data.onlyicon)}"
            data-icon="${data.icon||data.type.toLowerCase()}">
        <span class="contactText">${data.contact}</span>
    </a>`;

const activityDateTemplate = (data) => html`
    <span class="date" data-empty="${intBool(!data.date)}">${data.date}</span>`;
const descriptionListItemTemplate = (data) => html`
    <li class="descriptionItem">${data.text}</li>`;
const descriptionListTemplate = (data) => html`
    <ul class="description">${data.items}</ul>`;
const descriptionTextTemplate = (data) => html`
    <span class="description">${data.text}</span>`;
const timedActivityTemplate = (data) => html`
    <div class="activity tworows"
            data-has-title="${intBool(data.title)}"
            data-has-link="${intBool(data.link)}"
            data-has-period="${intBool(data.periodFrom||data.periodTo)}"
            data-has-subtitle="${intBool(data.subtitle)}"
            data-has-location="${intBool(data.location)}">
        <span class="title">${data.title}</span>
        <a class="link" href="${data.link}" target="_blank">${data.linkText||data.link}</a>
        <span class="period">
            ${data.periodFrom === undefined ? "" : activityDateTemplate({date: data.periodFrom})}
            ${data.periodTo === undefined ? "" : activityDateTemplate({date: data.periodTo})}
        </span>
        <span class="subtitle">${data.subtitle}</span>
        <span class="location">${data.location}</span>
        ${data.description}
    </div>`;

const skillTemplate = (data) => html`
    <span class="skill" data-level="${data.level}">${data.name}</span>`;
const skillGroupTemplate = (data) => html`
    <div class="skillGroup">
        <div class="skillGroupName">${data.name}:</div>
        <div class="skillsContainer">${data.skills}</div>
    </div>`;


const renderSections = (sectionsData) => {
    const sections = [];
    for (const [sectionId, sectionData] of Object.entries(sectionsData)) {
        const data = {...sectionData};
        data.id = sectionId;
        let sectionInner;
        if (data.type == 'header')
            sectionInner = makeHeaderSection(data);
        else if (data.type == 'text')
            sectionInner = textSectionTemplate(data);
        else if (data.type == 'list')
            sectionInner = makeListSection(data);
        else if (data.type == 'skills')
            sectionInner = makeSkillsSection(data);
        const section = sectionTemplate({id: data.id, inner: sectionInner});
        sections.push(section);
    }
    render(sections, document.querySelector('#cv'));
};

const makeHeaderSection = (headerData) => {
    const data = {...headerData};
    data.contacts = data.contacts.map((contact) => contactTemplate(contact));
    return headerSectionTemplate(data);
};
const makeListSection = (listData) => {
    const data = {...listData};
    if (data.listType == "work")
        data.content = makeWorkList(data.content);
    else if (data.listType == "projects")
        data.content = makeProjectsList(data.content);
    else if (data.listType == "education")
        data.content = makeEducationList(data.content);
    return listSectionTemplate(data);
};
const makeSkillsSection = (skillsData) => {
    const data = {...skillsData};
    data.content = makeSkills(data.content);
    return skillsSectionTemplate(data);
};

const makeWorkList = (workData) => {
    const activitiesData = workData.map((job) => ({
        title: job.company,
        periodFrom: job.period[0],
        periodTo: job.period[1],
        subtitle: job.jobTitle,
        link: job.link,
        linkText: job.linkText,
        location: job.location,
        description: job.keyPoints,
    }));
    return makeActivities(activitiesData);
};
const makeProjectsList = (projectsData) => {
    const activitiesData = projectsData.map((project) => ({
        title: project.name,
        periodFrom: project.period ? project.period[0] : undefined,
        periodTo: project.period ? project.period[1] : undefined,
        subtitle: project.subtitle,
        link: project.link,
        linkText: project.linkText,
        description: project.features,
    }));
    return makeActivities(activitiesData);
};
const makeEducationList = (educationData) => {
    const activitiesData = educationData.map((edu) => ({
        title: edu.institution,
        periodFrom: edu.period[0],
        periodTo: edu.period[1],
        location: edu.location,
        subtitle: edu.course,
        link: edu.link,
        linkText: edu.linkText,
        description: edu.description,
    }));
    return makeActivities(activitiesData);
};

const makeActivities = (activitiesData) => {
    return activitiesData.map((activity) => makeTimedActivity(activity));
};
const makeTimedActivity = (activityData) => {
    const data = {...activityData};
    if (Array.isArray(data.description))
        data.description = makeDescriptionList(data.description);
    else if (data.description != null)
        data.description = descriptionTextTemplate({text: data.description});
    return timedActivityTemplate(data);
};
const makeDescriptionList = (descriptionList) => {
    const items = descriptionList.map((item) => descriptionListItemTemplate({text: item}));
    return descriptionListTemplate({items: items});
};

const makeSkills = (skillsData) => {
    const skillGroupsHTML = [];
    for (const [skillGroupName, skills] of Object.entries(skillsData)) {
        const skillsHTML = skills.map((skill) => skillTemplate(skill));
        skillGroupsHTML.push(skillGroupTemplate(
            {name: skillGroupName, skills: skillsHTML}
        ));
    }
    return skillGroupsHTML
};


export const renderCV = (data) => {
    renderSections(data.sections);
};
